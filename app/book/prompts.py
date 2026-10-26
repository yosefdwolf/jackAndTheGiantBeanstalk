"""Builds every image prompt from the style, the story and the casting. No prompt text lives elsewhere.

Wording here was tuned by hand in the OpenAI Playground before it went into code.
"""
from .story import HERO, Casting, Character, PageSpec, Story
from .styles import ArtStyle

NO_TEXT = "No text, letters, numbers or signs anywhere in the image."

DESCRIBE_FACE = (
    "Describe this child's face for an illustrator who must make it recognizable, in 2-3 short "
    "lines: hair (colour, length, texture, style), face shape, eyes, brows, nose, smile, skin tone, "
    "approximate age, and any glasses, freckles or other distinctive features. Facts only."
)


class PromptBuilder:
    def __init__(self, style: ArtStyle, story: Story, casting: Casting):
        self.style, self.story, self.casting = style, story, casting

    def _style_lines(self) -> list[str]:
        return [f"Style: {self.style.description}", f"World: {self.story.world}"]

    def hero_sheet(self, face_description: str = "") -> str:
        """Prompt for turning the uploaded photo into the hero's reference sheet."""
        described = f" Distinctive features to keep: {face_description}." if face_description else ""
        return "\n".join([
            "Create a character reference portrait of the child in the photo, as the hero of a "
            "picture book.",
            f"Style: {self.style.description} {self.style.sheet_notes}",
            "Keep the child recognizable: same face shape, hairstyle and hair colour, skin tone, eye "
            "colour, apparent age, and any glasses or freckles. Redraw from scratch; do not trace or "
            "filter the photo." + described,
            f"Head and shoulders, facing the viewer, gentle smile. Outfit: {self.story.hero_outfit}. "
            "Plain soft warm-grey background.",
            NO_TEXT,
        ])

    def character_sheet(self, character: Character) -> str:
        """Prompt for a supporting character's sheet. Made once and committed; see scripts/."""
        return "\n".join([
            "Character reference sheet for a picture book.",
            f"Style: {self.style.description} {self.style.sheet_notes}",
            f"World: {self.story.world}",
            f"One character, full body, facing the viewer, on a plain warm-grey background: "
            f"{self.casting.fill(character.name)}, {character.description}.",
            "A single front view only: no turnaround, no side or back views, no close-up panels.",
            NO_TEXT,
        ])

    def page(self, spec: PageSpec) -> str:
        """Prompt for one illustrated page. Reference images are attached in spec.cast order."""
        c = self.casting
        refs = []
        for i, key in enumerate(spec.cast, 1):
            if key == HERO:
                refs.append(f"Image {i} is {c.hero_name}: use {c.fill('{him}')} exactly (same face, hair, "
                            f"skin tone, and outfit: {self.story.hero_outfit}).")
            else:
                refs.append(f"Image {i} is {c.name_of(key)}: draw them exactly as shown.")
        names = [c.name_of(k) for k in spec.cast]
        only = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else names[0]
        return "\n".join([
            " ".join(refs),
            *self._style_lines(),
            f"Wide picture-book illustration. {NO_TEXT}",
            f"Scene: {c.fill(spec.scene)}",
            f"Mood and light: {c.fill(spec.mood)}",
            f"Composition: {c.fill(spec.composition)}",
            f"Only these characters appear: {only}. No other people or animals.",
        ])
