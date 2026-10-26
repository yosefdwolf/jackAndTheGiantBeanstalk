"""The story file (stories/*.yaml) loaded into typed objects, plus per-book name and pronoun filling."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORY = ROOT / "stories" / "jack_and_the_beanstalk.yaml"
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


@dataclass(frozen=True)
class Story:
    title: str
    style: str
    world: str
    hero_names: dict
    hero_outfit: str
    characters: dict[str, Character]
    pages: tuple[PageSpec, ...] = field(default_factory=tuple)


TEXT_ZONES = {"bottom", "top", "bottom-dark"}


def load_story(path: Path = DEFAULT_STORY) -> Story:
    raw = yaml.safe_load(Path(path).read_text())
    characters = {k: Character(k, v["name"], v["description"]) for k, v in raw.get("characters", {}).items()}
    pages = []
    for i, p in enumerate(raw["pages"], 1):
        spec = PageSpec(number=i, type=p["type"], text=p.get("text", ""), cast=tuple(p.get("cast", ())),
                        scene=p.get("scene", ""), mood=p.get("mood", ""),
                        composition=p.get("composition", ""), text_zone=p.get("text_zone", "bottom"))
        unknown = [c for c in spec.cast if c != HERO and c not in characters]
        if unknown:
            raise ValueError(f"Page {i} casts unknown characters: {unknown}")
        if spec.text_zone not in TEXT_ZONES:
            raise ValueError(f"Page {i} has unknown text_zone {spec.text_zone!r}")
        pages.append(spec)
    return Story(title=raw["title"], style=raw["style"], world=raw["world"],
                 hero_names=raw["hero"]["names"], hero_outfit=raw["hero"]["outfit"],
                 characters=characters, pages=tuple(pages))


@dataclass(frozen=True)
class Casting:
    """Who the uploaded child plays: fills {hero}, {he}, {his}, {him} (and capitalized forms)."""
    story: Story
    gender: str = "boy"

    @property
    def hero_name(self) -> str:
        return self.story.hero_names[self.gender]

    def fill(self, text: str) -> str:
        words = {"hero": self.hero_name, **PRONOUNS[self.gender]}
        words |= {k.capitalize(): v.capitalize() for k, v in words.items() if k != "hero"}
        return text.format(**words)

    def name_of(self, key: str) -> str:
        return self.hero_name if key == HERO else self.fill(self.story.characters[key].name)
