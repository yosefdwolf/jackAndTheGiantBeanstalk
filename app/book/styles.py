"""Art styles. A book picks one style and uses its exact wording in every image call.

To add a style: subclass ArtStyle, then register it in STYLES. Nothing else changes.
"""
from abc import ABC, abstractmethod


class ArtStyle(ABC):
    key: str

    @property
    @abstractmethod
    def description(self) -> str:
        """The style sentence. Sent unchanged in every call so the look never drifts mid-book."""

    @property
    @abstractmethod
    def sheet_notes(self) -> str:
        """How to render a character reference sheet in this style."""

    @property
    def avoid(self) -> str:
        return "No text, letters, numbers or signs anywhere in the image. Nothing photographic."


class Animated3DStyle(ArtStyle):
    key = "animated3d"

    @property
    def description(self) -> str:
        return "Modern 3D animated feature — rounded forms, large expressive eyes, soft rim light."

    @property
    def sheet_notes(self) -> str:
        return "Smooth stylized skin, simplified features, soft studio lighting."


STYLES: dict[str, ArtStyle] = {s.key: s for s in (Animated3DStyle(),)}


def get_style(key: str) -> ArtStyle:
    try:
        return STYLES[key]
    except KeyError:
        raise ValueError(f"Unknown style {key!r}. Known: {', '.join(STYLES)}") from None
