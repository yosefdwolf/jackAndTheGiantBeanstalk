"""The scene bible: every page's scene, drawn once per story without the hero, kept in the database (`scenes`).
Each book then adds its child into the page's scene (PromptBuilder.on_scene), so every book shares the same
places, characters, light and plain space for the words.

A scene's key covers everything that shapes it: its prompt, the character pictures and earlier scenes sent with
it (`see_pages:`), and the image model. Change any of them and the next book (or the admin's "Draw the scenes")
draws a new one; old ones stay. Pages without the hero don't need a scene: the whole page is shared (jobs.py).
"""
import asyncio
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import defer

from ..db.models import Scene
from ..db.session import session
from .log import record
from .prompts import PromptBuilder
from .providers import PAGE_SIZE, ImageProvider
from .story import HERO, PageSpec, Story

_locks: dict[tuple, asyncio.Lock] = {}  # one drawing per page, even with books running at once


def needs_scene(spec: PageSpec) -> bool:
    return spec.type == "illustrated" and HERO in spec.cast


def _key(prompt: str, refs: list[tuple[str, bytes]], provider: ImageProvider) -> str:
    h = hashlib.sha1("\n".join([prompt, provider.name, str(provider.model), str(provider.quality)]).encode())
    for name, data in refs:
        h.update(name.encode() + hashlib.sha1(data).digest())
    return h.hexdigest()


async def _inputs(story: Story, spec: PageSpec, prompts: PromptBuilder, provider: ImageProvider,
                  sheets: dict[str, bytes], gate) -> tuple[str, list[tuple[str, bytes]]]:
    """The scene's prompt and pictures. Earlier scenes it sees are made (or found) first."""
    pages = {p.number: p for p in story.pages}
    earlier = tuple(n for n in spec.see if n in pages and needs_scene(pages[n]))
    seen = [await scene_for(story, pages[n], prompts, provider, sheets, gate) for n in earlier]
    refs = [(f"{k}.png", sheets[k]) for k in spec.cast if k != HERO]
    refs += [(f"scene-{n}.png", png) for n, png in zip(earlier, seen)]
    return prompts.scene(spec, earlier), refs


async def saved(story: Story, spec: PageSpec, prompts: PromptBuilder, provider: ImageProvider,
                sheets: dict[str, bytes]) -> Scene | None:
    """The scene books would use now, if it's been drawn (without its image loaded). Draws nothing."""
    pages = {p.number: p for p in story.pages}
    earlier = []
    for n in spec.see:
        if n in pages and needs_scene(pages[n]):
            row = await saved(story, pages[n], prompts, provider, sheets)
            if row is None:
                return None
            earlier.append((n, await image(row.id)))
    refs = [(f"{k}.png", sheets[k]) for k in spec.cast if k != HERO] + [(f"scene-{n}.png", p) for n, p in earlier]
    key = _key(prompts.scene(spec, tuple(n for n, _ in earlier)), refs, provider)
    async with session() as s:
        return (await s.execute(select(Scene).options(defer(Scene.image)).where(Scene.key == key)
                                .order_by(Scene.id.desc()))).scalars().first()


async def image(scene_id: int) -> bytes:
    async with session() as s:
        return (await s.execute(select(Scene.image).where(Scene.id == scene_id))).scalar_one()


async def scene_for(story: Story, spec: PageSpec, prompts: PromptBuilder, provider: ImageProvider,
                    sheets: dict[str, bytes], gate=None, redraw: bool = False) -> bytes:
    """The page's scene: the saved one, or drawn now (about 4 cents) and saved. `redraw` always draws anew."""
    # Per event loop: a lock belongs to the loop that made it (tests run several).
    async with _locks.setdefault((id(asyncio.get_running_loop()), story.key, spec.number), asyncio.Lock()):
        prompt, refs = await _inputs(story, spec, prompts, provider, sheets, gate)
        key = _key(prompt, refs, provider)
        if not redraw:
            async with session() as s:
                found = (await s.execute(select(Scene.image).where(Scene.key == key).order_by(Scene.id.desc())
                                         )).scalars().first()
            if found is not None:
                return found
        label = f"scene {spec.number}"
        await record("INFO", label, "drawing", story=story.key, reason="asked for again" if redraw else "new")
        async with (gate or asyncio.Semaphore(1)):
            result = (await provider.edit(label=label, refs=refs, prompt=prompt, size=PAGE_SIZE) if refs
                      else await provider.generate(label, prompt, PAGE_SIZE))
        async with session() as s:
            s.add(Scene(key=key, story_key=story.key, page_number=spec.number, image=result.png, prompt=prompt,
                        cost=result.cost))
            await s.commit()
        return result.png


async def draw_all(story: Story, prompts: PromptBuilder, provider: ImageProvider, sheets: dict[str, bytes],
                   at_once: int = 7) -> int:
    """Every scene the story's pages need that isn't drawn yet. How many there are now."""
    gate = asyncio.Semaphore(at_once)
    specs = [p for p in story.pages if needs_scene(p)]
    await asyncio.gather(*(scene_for(story, p, prompts, provider, sheets, gate) for p in specs))
    return len(specs)
