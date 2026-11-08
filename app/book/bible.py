"""The character bible, in the database: `stories`, their `characters`, and every `character_pictures` version.

The story files are the master copy. On every startup, sync_stories mirrors each file into `stories` and
`characters` (a file that's gone leaves its story inactive, so old books still open) and imports any picture
kept at assets/characters/<story>/<key>.png. Nobody edits these tables by hand.

Which picture a book uses, for each character (nothing is ever replaced):
1. `picture: wolf-2` in the story file: always that version (`other_story/wolf-2` for another story's).
   The description is then ignored.
2. The newest version drawn (or imported) from the character's current description.
3. Otherwise a new version is drawn from the description (about 4 cents) and saved as <key>-<n>. So changing a
   description draws a new version; the old ones stay, to pin again any time.
"""
import asyncio
import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import defer

from ..db.models import Book, CharacterPicture, StoryCharacter, StoryRow, now
from ..db.session import session
from .cast import repo_sheet
from .log import record
from .prompts import PromptBuilder
from .providers import SHEET_SIZE, ImageProvider, MockImageProvider
from .story import Casting, Story, all_stories, story_file
from .styles import get_style

_locks: dict[tuple[str, str], asyncio.Lock] = {}  # one writer per story / character, even with books running at once


def _lock(*key: str) -> asyncio.Lock:
    # Per event loop: a lock belongs to the loop that made it (tests run several).
    return _locks.setdefault((id(asyncio.get_running_loop()), *key), asyncio.Lock())


def prompts_for(story: Story) -> PromptBuilder:
    return PromptBuilder(get_style(story.style), story, Casting(story))


def _file_hash(story: Story) -> str:
    path = story_file(story)
    data = path.read_bytes() if path.exists() else repr(story).encode()
    return hashlib.sha1(data).hexdigest()[:16]


# --- mirroring the story files ---------------------------------------------------------------------

async def ensure_story(story: Story) -> int:
    """The story's row and its characters' rows, made or brought up to date from the story file. Its id."""
    async with _lock("story", story.key):
        async with session() as s:
            row = (await s.execute(select(StoryRow).where(StoryRow.key == story.key))).scalar_one_or_none()
            if row is None:
                row = StoryRow(key=story.key)
                s.add(row)
            row.title, row.file_hash, row.active, row.synced_at = story.title, _file_hash(story), True, now()
            await s.flush()
            existing = {c.key: c for c in (await s.execute(
                select(StoryCharacter).where(StoryCharacter.story_id == row.id))).scalars()}
            for key, character in story.characters.items():
                c = existing.get(key) or StoryCharacter(story_id=row.id, key=key)
                c.name, c.description, c.pin = character.name, character.description, character.picture or None
                s.add(c)
            await s.commit()
            return row.id


async def _import_kept_pictures(story: Story) -> None:
    """A picture kept at assets/characters/<story>/<key>.png becomes a version, once."""
    prompts = prompts_for(story)
    for key, character in story.characters.items():
        kept = repo_sheet(story.key, key)
        if not kept.exists():
            continue
        async with _lock("character", story.key, key):
            c = await _character(story, key)
            async with session() as s:
                done = (await s.execute(select(func.count()).where(CharacterPicture.character_id == c.id,
                                                                   CharacterPicture.source == "imported"))).scalar()
            if not done:
                picture = await _save(c, kept.read_bytes(), prompts.character_sheet(character), "imported", None)
                if c.picture_id is None and not c.pin:
                    await _use(c, picture.id)


async def sync_stories() -> None:
    """On startup: every story file into the tables, kept pictures imported, books linked to their story."""
    stories = all_stories()
    for story in stories:
        await ensure_story(story)
        await _import_kept_pictures(story)
    async with session() as s:
        await s.execute(update(StoryRow).where(StoryRow.key.not_in([st.key for st in stories])).values(active=False))
        for row in (await s.execute(select(StoryRow.id, StoryRow.key))).all():
            await s.execute(update(Book).where(Book.story_key == row.key, Book.story_id.is_(None))
                            .values(story_id=row.id))
        await s.commit()
    await record("INFO", "stories", "synced", stories=len(stories))


# --- choosing a picture ---------------------------------------------------------------------------

@dataclass
class Choice:
    """Which picture a character uses right now, and why (for the admin's Characters tab)."""
    picture: CharacterPicture | None  # without its image loaded
    why: str  # pinned | pinned but missing | matches the description | not drawn yet | description changed


async def _character(story: Story, key: str) -> StoryCharacter:
    async with session() as s:
        c = (await s.execute(select(StoryCharacter).join(StoryRow)
                             .where(StoryRow.key == story.key, StoryCharacter.key == key))).scalar_one_or_none()
    wanted = story.characters[key]
    if c is None or c.description != wanted.description or (c.pin or "") != wanted.picture:
        await ensure_story(story)  # a story the startup sync hasn't seen (or changed since): mirror it now
        return await _character(story, key)
    return c


async def choose(story: Story, key: str, prompts: PromptBuilder) -> Choice:
    """The picture this character would use, without drawing anything."""
    c = await _character(story, key)
    async with session() as s:
        if c.pin:
            story_key, _, name = c.pin.rpartition("/")
            pinned = (await s.execute(  # names carry their character (wolf-2), so story + name finds it
                select(CharacterPicture).options(defer(CharacterPicture.image))
                .join(StoryCharacter, CharacterPicture.character_id == StoryCharacter.id).join(StoryRow)
                .where(StoryRow.key == (story_key or story.key), CharacterPicture.name == name))).scalars().first()
            if pinned is not None:
                return Choice(pinned, "pinned")
        versions = (await s.execute(select(CharacterPicture).options(defer(CharacterPicture.image))
                                    .where(CharacterPicture.character_id == c.id)
                                    .order_by(CharacterPicture.id.desc()))).scalars().all()
    prompt = prompts.character_sheet(story.characters[key])
    match = next((v for v in versions if v.prompt == prompt), None)
    if c.pin:
        return Choice(match, "pinned but missing")
    return Choice(match, "matches the description" if match else "description changed" if versions else "not drawn yet")


async def _save(c: StoryCharacter, png: bytes, prompt: str, source: str, cost) -> CharacterPicture:
    async with session() as s:
        n = (await s.execute(select(func.count()).where(CharacterPicture.character_id == c.id))).scalar()
        picture = CharacterPicture(character_id=c.id, name=f"{c.key}-{n + 1}", image=png, prompt=prompt,
                                   source=source, cost=cost)
        s.add(picture)
        await s.commit()
        return picture


async def _use(c: StoryCharacter, picture_id: int) -> bytes:
    """Mark the picture as the one books use, and return it."""
    async with session() as s:
        if c.picture_id != picture_id:
            await s.execute(update(StoryCharacter).where(StoryCharacter.id == c.id).values(picture_id=picture_id))
            await s.commit()
        return (await s.execute(select(CharacterPicture.image).where(CharacterPicture.id == picture_id))).scalar_one()


async def sheet(story: Story, key: str, prompts: PromptBuilder, provider: ImageProvider) -> bytes:
    character = story.characters[key]
    async with _lock("character", story.key, key):
        chosen = await choose(story, key, prompts)
        c = await _character(story, key)
        if chosen.why == "pinned but missing":
            await record("WARNING", f"{key} sheet", "pinned picture missing", picture=character.picture,
                         note="using the description instead")
        if chosen.picture is not None:
            return await _use(c, chosen.picture.id)
        prompt = prompts.character_sheet(character)
        kept = repo_sheet(story.key, key)
        if kept.exists():  # kept in the repo but not imported yet (a story added since startup)
            return await _use(c, (await _save(c, kept.read_bytes(), prompt, "imported", None)).id)
        if isinstance(provider, MockImageProvider):  # pretend books get a placeholder, never saved
            return MockImageProvider._draw(f"{key} sheet", SHEET_SIZE, None, 0)
        await record("INFO", f"{key} sheet", "drawing", story=story.key, reason=chosen.why)
        result = await provider.generate(f"{key} sheet", prompt, SHEET_SIZE)
        return await _use(c, (await _save(c, result.png, prompt, "drawn", result.cost)).id)


async def draw_new(story: Story, key: str, provider: ImageProvider) -> tuple[CharacterPicture, bool]:
    """An admin asked for a (new) drawing from the current description: always a new version, used from now on
    unless the story file pins another. Returns the picture and whether books use it."""
    prompt = prompts_for(story).character_sheet(story.characters[key])
    async with _lock("character", story.key, key):
        c = await _character(story, key)
        await record("INFO", f"{key} sheet", "drawing", story=story.key, reason="asked for in the admin site")
        result = await provider.generate(f"{key} sheet", prompt, SHEET_SIZE)
        picture = await _save(c, result.png, prompt, "drawn", result.cost)
        if not c.pin:
            await _use(c, picture.id)
        return picture, not c.pin


async def add_upload(story: Story, key: str, png: bytes) -> tuple[CharacterPicture, bool]:
    """A picture an admin uploaded for a character: a new version, and the one books use from now on (unless
    the story file pins another). Counts as drawn from the current description, so it stays until that changes.
    Returns the picture and whether books use it."""
    prompt = prompts_for(story).character_sheet(story.characters[key])
    async with _lock("character", story.key, key):
        c = await _character(story, key)
        picture = await _save(c, png, prompt, "uploaded", None)
        if not c.pin:
            await _use(c, picture.id)
        await record("INFO", f"{key} sheet", "uploaded", story=story.key, picture=picture.name)
        return picture, not c.pin


async def current(story: Story) -> dict[str, bytes]:
    """The pictures books would use now, for the characters that have one. Draws and changes nothing."""
    prompts, out = prompts_for(story), {}
    for key in story.characters:
        chosen = await choose(story, key, prompts)
        if chosen.picture is not None:
            async with session() as s:
                out[key] = (await s.execute(select(CharacterPicture.image)
                                            .where(CharacterPicture.id == chosen.picture.id))).scalar_one()
    return out


async def sheets_for(story: Story, prompts: PromptBuilder, provider: ImageProvider) -> dict[str, bytes]:
    """Every character the story's pages use, drawn at the same time if any are missing."""
    keys = sorted({k for page in story.pages for k in page.cast if k in story.characters})
    pngs = await asyncio.gather(*(sheet(story, k, prompts, provider) for k in keys))
    return dict(zip(keys, pngs))
