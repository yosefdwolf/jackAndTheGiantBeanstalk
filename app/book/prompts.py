"""Builds every image prompt from the style, the story and the casting. No prompt text lives elsewhere.

Wording here was tuned by hand in the OpenAI Playground before it went into code.
"""
import re

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
            f"One single head-and-shoulders portrait, facing the viewer, gentle smile. Outfit: {self.story.hero_outfit}. "
            "Plain soft warm-grey background. Only one view of the child: not a character sheet, turnaround, grid "
            "or several poses.",
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
        """Prompt for a whole page drawn from the cast's sheets (attached in spec.cast order): a page without
        the hero (shared by every book). Pages with the hero are drawn on their scene (on_scene)."""
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
            *([f"Costumes (exactly as on the other pages): {c.fill(spec.costume)}"] if spec.costume else []),
            f"Only these characters appear: {only}. No other people or animals.",
        ])

    # --- the scene bible: each page's scene drawn once per story, then the child added in every book ---------

    def _neutral(self, text: str) -> str:
        """Story text with the hero as "the hero", so a scene is the same for a boy's and a girl's book."""
        words = {"hero": "the hero", "he": "the hero", "his": "the hero's", "him": "the hero"}
        words |= {k.capitalize(): v.capitalize() for k, v in words.items() if k != "hero"}
        return re.sub(r"(^|[.!?:]\s+)the hero", r"\1The hero", text.format(**words))

    def scene(self, spec: PageSpec, earlier: tuple[int, ...] = ()) -> str:
        """Prompt for a page's scene, without the hero: drawn once per story and kept (app/book/scenes.py).
        Attached: the other characters' sheets in cast order, then the scenes of `earlier` pages."""
        others = [k for k in spec.cast if k != HERO]
        refs = [f"Image {i} is {self._neutral(self.story.characters[k].name)}: draw them exactly as shown."
                for i, k in enumerate(others, 1)]
        refs += [f"Image {i} is the scene of page {n}, the moment just before: keep the same place, furniture, "
                 "light and costumes, so the two pages follow on." for i, n in enumerate(earlier, len(others) + 1)]
        names = [self._neutral(self.story.characters[k].name) for k in others]
        cast = (f"Only these characters appear: {', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else names[0]}. "
                "No other people or animals.") if names else "No people or animals at all."
        return "\n".join([
            *([" ".join(refs)] if refs else []),
            *self._style_lines(),
            f"Wide picture-book illustration: the background scene for one page. {NO_TEXT}",
            "The hero, a child, is added into this picture later, so do NOT draw the hero or any child. Leave the "
            "spot where the hero is described clear and empty, with nothing in front of it, so the hero can be "
            "added there; everything else in the scene is drawn exactly as described.",
            f"Scene: {self._neutral(spec.scene)}",
            f"Mood and light: {self._neutral(spec.mood)}",
            f"Composition: {self._neutral(spec.composition)} The hero's spot must not be in that space for text.",
            *([f"Costumes (exactly as on the other pages): {self._neutral(spec.costume)}"] if spec.costume else []),
            cast,
        ])

    def swap(self, spec: PageSpec) -> str:
        """Prompt for a book's page from a scene that has a stand-in child in it (image 2): the stand-in is replaced
        by the hero (image 1), keeping the stand-in's pose, place and size. Being tried on single pages first."""
        c = self.casting
        text_area = {"top": "top third", "bottom": "bottom third", "bottom-dark": "bottom quarter"}[spec.text_zone]
        return "\n".join([
            f"Image 1 is {c.hero_name}: use {c.fill('{him}')} exactly (same face, hair, skin tone, and outfit: "
            f"{self.story.hero_outfit}). Image 2 is this page's finished scene, with a stand-in child in it.",
            f"Draw image 2 again with the stand-in child replaced completely by {c.hero_name} from image 1: "
            f"{c.fill('{his}')} own face, hair, skin tone and build, taken only from image 1, never from the stand-in. "
            "Keep the stand-in's pose, place, size and what they are holding. Keep everything else in image 2 exactly "
            "the same: the place, the other characters, the light, the colours and the composition.",
            *self._style_lines(),
            f"Wide picture-book illustration. {NO_TEXT}",
            f"Scene: {c.fill(spec.scene)}",
            f"Keep {c.hero_name}'s face out of the {text_area} of the picture: it stays plain, for the story text.",
            "Only the child changes; nothing else in the picture does.",
        ])

    def on_scene(self, spec: PageSpec) -> str:
        """Prompt for a book's page: the hero (image 1) added into the page's saved scene (image 2)."""
        c = self.casting
        text_area = {"top": "top third", "bottom": "bottom third", "bottom-dark": "bottom quarter"}[spec.text_zone]
        return "\n".join([
            f"Image 1 is {c.hero_name}: use {c.fill('{him}')} exactly (same face, hair, skin tone, and outfit: "
            f"{self.story.hero_outfit}). Image 2 is this page's finished scene.",
            f"Draw image 2 again with {c.hero_name} added into it, as described below. Keep everything else in image "
            "2 exactly the same: the place, the other characters, the light, the colours and the composition.",
            *self._style_lines(),
            f"Wide picture-book illustration. {NO_TEXT}",
            f"Scene: {c.fill(spec.scene)}",
            f"Keep {c.hero_name}, and above all {c.fill('{his}')} face, out of the {text_area} of the picture: it "
            "stays plain, for the story text.",
            f"{c.hero_name} is the only person added; nothing else changes.",
        ])

