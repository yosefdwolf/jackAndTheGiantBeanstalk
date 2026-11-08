"""The story file (stories/*.yaml) loaded into typed objects, plus per-book name and pronoun filling."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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

    @property
    def slug(self) -> str:
        """Its address on the site: /stories/<slug>."""
        return self.key.replace("_", "-")


TEXT_ZONES = {"bottom", "top", "bottom-dark"}


def load_story(path: Path = DEFAULT_STORY) -> Story:
    raw = yaml.safe_load(Path(path).read_text())
    characters = {k: Character(k, v["name"], v["description"]) for k, v in raw.get("characters", {}).items()}
    pages = []
    for i, p in enumerate(raw["pages"], 1):
        spec = PageSpec(number=i, type=p["type"], text=p.get("text", ""), cast=tuple(p.get("cast", ())),
                        scene=p.get("scene", ""), mood=p.get("mood", ""),
                        composition=p.get("composition", ""), text_zone=p.get("text_zone", "bottom"),
                        progress=p.get("progress", ""))
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
                 cover_page=int(raw.get("cover_page", 0)), site=raw.get("site", {}))


def all_stories() -> list[Story]:
    """Every story in the library, in title order."""
    return sorted((load_story(p) for p in STORIES.glob("*.yaml")), key=lambda s: s.title)


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
