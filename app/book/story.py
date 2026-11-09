"""The story file (stories/*.yaml) loaded into typed objects, plus per-book name and pronoun filling."""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("book")

ROOT = Path(__file__).resolve().parents[2]
STORIES = ROOT / "stories"
DEFAULT_STORY = STORIES / "jack_and_the_beanstalk.yaml"
HERO = "hero"  # cast key for the uploaded child

PRONOUNS = {
    "boy": {"he": "he", "his": "his", "him": "him"},
    "girl": {"he": "she", "his": "her", "him": "her"},
}


@dataclass(frozen=True)
class Character:
    key: str
    name: str
    description: str
    picture: str = ""  # optional: a saved picture's name (wolf-2, or other_story/wolf-2) to always use


@dataclass(frozen=True)
class PageSpec:
    number: int
    type: str
    text: str = ""
    cast: tuple[str, ...] = ()
    scene: str = ""
    mood: str = ""
    composition: str = ""
    text_zone: str = "bottom"
    progress: str = ""  # the witty line the progress card shows while this picture is drawn
    costume: str = ""   # what characters wear on this page, worded the same on every page they wear it
    see: tuple[int, ...] = ()  # earlier pages sent along as pictures, to keep the same place (see_pages:)
    focus: str = ""  # what the page is about; the words go where they don't cover it


@dataclass(frozen=True)
class Story:
    title: str
    style: str
    world: str
    theme: str
    hero_names: dict
    hero_outfit: str
    characters: dict[str, Character]
    pages: tuple[PageSpec, ...] = field(default_factory=tuple)
    key: str = ""      # the file's name: stories/<key>.yaml
    blurb: str = ""    # the library card's one or two sentences
    library_cover: str = ""  # the library's cover picture (a /static/ path)
    cover_page: int = 0      # each book's bookshelf cover: this page, cropped upright around the hero
    site: dict = field(default_factory=dict)  # the story page's own words (button, titles, placeholders)
    pronouns: dict = field(default_factory=dict)  # the form's boy/girl question and its two buttons' labels
    draft: bool = False  # only admins see it, to try it before customers can buy it
    cover: dict = field(default_factory=dict)  # the library cover's scene / mood / composition (scripts/make_cover.py)
    look: dict = field(default_factory=dict)   # the story page's colours and painted backdrop (shared story theme)

    @property
    def slug(self) -> str:
        """Its address on the site: /stories/<slug>."""
        return self.key.replace("_", "-")


TEXT_ZONES = {"bottom", "top", "bottom-dark"}

# The one template every story follows: 20 painted pages, then the About Me page. Page N keeps its words in
# the same place in every story (so the layout is shared), which is this list. A story file that doesn't fit
# isn't shown in the library; check_story says why.
TEMPLATE_ZONES = ("bottom", "top", "bottom-dark", "top", "bottom", "bottom", "top", "bottom", "bottom", "bottom",
                  "bottom", "top", "bottom", "top", "top", "bottom", "top", "bottom", "top", "bottom")
LOOK_COLOURS = ("sky", "leaf", "leaf_deep", "accent", "accent_deep", "card", "card_edge", "ink", "ink_soft")
HEX = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
SITE_WORDS = ("heading", "go", "going", "growing", "binding", "failed", "hero_progress", "about_placeholder",
              "review_placeholder", "pdf_name", "musing")


def load_story(path: Path = DEFAULT_STORY) -> Story:
    raw = yaml.safe_load(Path(path).read_text())
    characters = {k: Character(k, v["name"], v["description"], str(v.get("picture") or ""))
                  for k, v in raw.get("characters", {}).items()}
    pages = []
    for i, p in enumerate(raw["pages"], 1):
        spec = PageSpec(number=i, type=p["type"], text=p.get("text", ""), cast=tuple(p.get("cast", ())),
                        scene=p.get("scene", ""), mood=p.get("mood", ""),
                        composition=p.get("composition", ""), text_zone=p.get("text_zone", "bottom"),
                        progress=p.get("progress", ""), costume=" ".join(str(p.get("costume", "")).split()),
                        see=tuple(int(n) for n in p.get("see_pages", ()) or ()), focus=p.get("focus", ""))
        unknown = [c for c in spec.cast if c != HERO and c not in characters]
        if unknown:
            raise ValueError(f"Page {i} casts unknown characters: {unknown}")
        if spec.text_zone not in TEXT_ZONES:
            raise ValueError(f"Page {i} has unknown text_zone {spec.text_zone!r}")
        pages.append(spec)
    return Story(title=raw["title"], style=raw["style"], world=raw["world"], theme=raw.get("theme", "default"),
                 hero_names=raw["hero"]["names"], hero_outfit=raw["hero"]["outfit"],
                 characters=characters, pages=tuple(pages), key=Path(path).stem,
                 blurb=" ".join(raw.get("blurb", "").split()), library_cover=raw.get("library_cover", ""),
                 cover_page=int(raw.get("cover_page", 0)), site=raw.get("site", {}),
                 pronouns=raw.get("pronouns", {}), draft=bool(raw.get("draft", False)),
                 cover=raw.get("cover", {}), look=raw.get("look", {}))


def check_story(story: Story) -> list[str]:
    """Everything that keeps a story file from fitting the template, in words. Empty means it's ready."""
    from .styles import STYLES
    problems = []
    if story.style not in STYLES:
        problems.append(f"style {story.style!r} isn't one of {sorted(STYLES)}")
    if not (story.hero_names.get("boy") and story.hero_names.get("girl")):
        problems.append("hero: names needs both boy and girl")
    problems += [f"pronouns: {k} is missing" for k in ("question", "boy", "girl") if not story.pronouns.get(k)]
    if story.look:
        colours = story.look.get("colors") or {}
        if colours:  # needed only by stories without a theme folder of their own
            problems += [f"look: colors: {k} is missing" for k in LOOK_COLOURS if k not in colours]
        problems += [f"look: colors: {k} must be a colour like #2f7d3a" for k, v in colours.items() if not HEX.match(str(v))]
        problems += [f"look: backdrop: {k} is missing" for k in ("wide", "tall") if not (story.look.get("backdrop") or {}).get(k)]
    if not story.blurb:
        problems.append("blurb (the library's description) is missing")
    problems += [f"site: {k} is missing" for k in SITE_WORDS if not story.site.get(k)]
    painted = [p for p in story.pages if p.type == "illustrated"]
    if len(painted) != len(TEMPLATE_ZONES) or [p.type for p in story.pages][-1:] != ["about_me"]:
        problems.append(f"needs {len(TEMPLATE_ZONES)} illustrated pages then an about_me page "
                        f"(has {len(painted)} illustrated, {len(story.pages)} in all)")
    for p, zone in zip(painted, TEMPLATE_ZONES):
        if p.text_zone != zone:
            problems.append(f"page {p.number}: text_zone must be {zone} (the template), not {p.text_zone}")
        problems += [f"page {p.number}: {k} is missing" for k in ("text", "scene", "mood", "composition", "progress")
                     if not getattr(p, k)]
        if not p.cast:
            problems.append(f"page {p.number}: cast is empty")
        problems += [f"page {p.number}: see_pages {n} must be an earlier painted page" for n in p.see
                     if n >= p.number or n not in {q.number for q in painted}]
    cover = next((p for p in painted if p.number == story.cover_page), None)
    if cover is None or HERO not in cover.cast:
        problems.append("cover_page must be a painted page with the hero in it")
    return problems


def all_stories() -> list[Story]:
    """Every story in the library (each file in stories/ that fits the template), in title order. A broken
    file is left out and logged, so it can never take the library down."""
    stories = []
    for path in STORIES.glob("*.yaml"):
        try:
            story = load_story(path)
            problems = check_story(story)
        except Exception as e:  # unreadable YAML, a missing key...
            problems = [f"{type(e).__name__}: {e}"]
        if problems:
            log.warning("story %s left out of the library: %s", path.name, "; ".join(problems))
            continue
        stories.append(story)
    return sorted(stories, key=lambda s: s.title)


def story_file(story: Story) -> Path:
    return STORIES / f"{story.key}.yaml"


def story_for(key: str | None) -> Story:
    """A book's story, by the key saved with it; Jack for books from before there were others."""
    path = STORIES / f"{key}.yaml" if key else DEFAULT_STORY
    return load_story(path if path.exists() else DEFAULT_STORY)


def story_by_slug(slug: str) -> Story | None:
    return next((s for s in all_stories() if s.slug == slug), None)


def display_name(name: str | None) -> str:
    """The name as the book prints it. Typed all in lowercase, each word gets a capital ("yosef wolf" ->
    "Yosef Wolf"). Any capital at all means they chose it, so it's kept as typed ("van Dyke", "McKenzie")."""
    words = (name or "").split()
    if any(not w.islower() for w in words):
        return " ".join(words)
    return " ".join(w[:1].upper() + w[1:] for w in words)


@dataclass(frozen=True)
class Casting:
    """Who the reader plays: fills {hero}, {he}, {his}, {him} (and capitalized forms).

    The Jack/Jane choice only picks the pronouns. With `name`, the story text says the reader's own name
    ("Yosef and his mother"). Image prompts use a casting without a name, so they always say the story's
    hero ("Jack") and nothing a person types ever goes into an image prompt.
    """
    story: Story
    gender: str = "boy"
    name: str | None = None

    @property
    def hero_name(self) -> str:
        return self.name or self.story.hero_names[self.gender]

    @property
    def story_hero(self) -> str:
        """The hero the story is about (Jack or Jane), whatever the reader is called."""
        return self.story.hero_names[self.gender]

    def fill(self, text: str) -> str:
        words = {"hero": self.hero_name, **PRONOUNS[self.gender]}
        words |= {k.capitalize(): v.capitalize() for k, v in words.items() if k != "hero"}
        return text.format(**words)

    def name_of(self, key: str) -> str:
        return self.hero_name if key == HERO else self.fill(self.story.characters[key].name)
