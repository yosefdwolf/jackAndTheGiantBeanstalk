"""Checks what the reader typed before anything is charged or drawn. The name goes on the cover and through the
story, and the About Me details are printed on the back cover, so nothing unkind or inappropriate gets in.

Two checks, both on OpenAI: its moderation model (free) on everything typed, and one short gpt-4.1-mini question
(about 0.01 cents) that judges what moderation can't: is the name a real-sounding name, and not an insult or an
epithet? Without OpenAI (the mock provider, or the API down) a short list of words catches the obvious ones."""
import json
import os
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

from .log import add_cost, record, step

FIELDS = {"name": "Your name", "age": "Age", "favourites": "Favourite things", "about": "More about you"}

# The obvious ones, for when the model can't be asked. The model's judgment is the real check.
# Whole words only, so "butterflies", "farther" and "Cassandra" are fine.
RUDE = re.compile(r"\b(stupid|idiot|dumb|moron|loser|ugly|fatso|poop\w*|butt(s|head|face)?|fart(s|y|face)?|"
                  r"sh[i1!*]t\w*|f[u*]ck\w*|b[i1!*]tch\w*|ass(hole)?|crap(py)?|nazis?|sexy?)\b", re.I)

ASK = """You check what a parent typed into a personalised children's picture book that will be printed.
The child's name goes on the cover ("Little Red Riding Hood, starring <name>") and through the story. The other
answers are printed on the back cover under "About Me".

Name: a real-sounding first name or nickname of a person, from any culture or language, is fine, including rare
or unusual spellings (Sarah, Xiomara, Oluwaseun, Mei, JJ, Bubba, Ana-Lucía, Zay). Refuse an insult, an epithet or
slur, a swear word, a body part or toilet word, a joke or a phrase, a sentence, a famous character (Shrek, Batman),
or random letters or keyboard mashing (asdfgh, qwerty, xxxx, zzzz) that no person is called.

Details (age, favourite things, more about the child): anything a child or parent might say is fine, including
silly or unusual things. Refuse swearing, insults about someone, anything sexual, hateful, cruel or graphically
violent, drugs or alcohol, and contact details (a phone number, an address, an email).

Answer in JSON only: {"ok": true} or {"ok": false, "field": "name"|"age"|"favourites"|"about",
"why": "<a few kind words for the parent, e.g. 'please use a real first name'>"}"""


@dataclass
class Problem:
    field: str  # name | age | favourites | about
    message: str


def message_for(field: str) -> str:
    if field == "name":
        return "Please use your real first name (or a nickname). It goes on the cover of a printed book."
    return f"Please change “{FIELDS[field]}”: it's printed on the back cover, so it needs to be kind and child-friendly."


def rule_check(answers: dict[str, str]) -> Problem | None:
    """No model needed: a name has to look like a name, and nothing can hold an obviously rude word."""
    name = answers.get("name", "").strip()
    if not re.search(r"[^\W\d_]", name) or len(name) > 40 or len(name.split()) > 4 or re.search(r"https?://|www\.|@", name):
        return Problem("name", message_for("name"))
    for field, value in answers.items():
        if RUDE.search(value):
            return Problem(field, message_for(field))
    return None


async def check(answers: dict[str, str], use_model: bool) -> Problem | None:
    """The first problem found, or None. `answers` maps name/age/favourites/about to what was typed."""
    answers = {k: v.strip() for k, v in answers.items() if v and v.strip()}
    if problem := rule_check(answers):
        await record("INFO", "about check", "refused", field=problem.field, by="rules")
        return problem
    if not use_model or not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        problem = await _ask_openai(answers)
    except Exception as e:  # the API down: the rules above already ran; don't stop a book over it
        await record("WARNING", "about check", "openai failed", error=type(e).__name__)
        return None
    if problem:
        await record("INFO", "about check", "refused", field=problem.field, by="openai")  # never what was typed
    return problem


async def _ask_openai(answers: dict[str, str]) -> Problem | None:
    client = AsyncOpenAI(max_retries=1, timeout=15)
    async with step("about check", call="moderations"):
        moderation = await client.moderations.create(
            model="omni-moderation-latest", input=[f"{FIELDS[k]}: {v}" for k, v in answers.items()])
    for field, result in zip(answers, moderation.results):
        if result.flagged:
            return Problem(field, message_for(field))

    model = os.getenv("VISION_MODEL", "gpt-4.1-mini")
    async with step("about check", call="chat.completions", model=model):
        resp = await client.chat.completions.create(
            model=model, max_tokens=80, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": ASK},
                      {"role": "user", "content": json.dumps({k: answers[k] for k in answers})}])
    add_cost((resp.usage.prompt_tokens * 0.40 + resp.usage.completion_tokens * 1.60) / 1e6)
    verdict = json.loads(resp.choices[0].message.content or "{}")
    if verdict.get("ok", True):
        return None
    field = verdict.get("field") if verdict.get("field") in FIELDS else "name"
    return Problem(field, message_for(field))
