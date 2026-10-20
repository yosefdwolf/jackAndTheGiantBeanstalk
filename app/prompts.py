"""Prompt builder. Order matters: identity first, then style, then scene, then composition.

The scenes are fixed, so each one is fully art-directed below rather than left to the model.
"""
from dataclasses import dataclass

# Fixed by the assignment. Not user-editable: the API and UI never accept scene text.
SCENES = (
    "Jack is planting the seed.",
    "Jack is climbing the beanstalk.",
)

# Shown under each image after the scene text, so the caption reads as a storybook line.
SCENE_DESCRIPTIONS = {
    SCENES[0]: (
        "Kneeling in the cottage garden at sunrise, Jack presses a single glowing magic bean "
        "into the freshly dug soil, hoping it was worth trading the cow for."
    ),
    SCENES[1]: (
        "High above the clouds, Jack hauls up the giant twisting beanstalk hand over hand, "
        "while the cottage and fields shrink to a tiny patchwork far below."
    ),
}


@dataclass(frozen=True)
class SceneBrief:
    action: str       # what Jack is doing, the core of the caption
    setting: str      # where and when
    props: str        # objects that must be visible
    pose: str         # body, hands, expression
    camera: str       # framing that keeps the face large
    lighting: str
    avoid: str        # common drifts that would make the picture wrong


SCENE_BRIEFS = {
    SCENES[0]: SceneBrief(
        action=(
            "Jack is planting a single magic bean: pushing one large, glowing, speckled bean "
            "into a small hole in freshly dug dark soil with the fingertips of one hand."
        ),
        setting=(
            "A small, poor vegetable garden behind a crooked thatched-roof cottage in the "
            "countryside, early morning. A worn wooden fence and rolling green hills behind."
        ),
        props=(
            "The bean is clearly visible between Jack's fingers, just entering the soil. A few "
            "more beans rest in Jack's other open palm. A small wooden trowel and a little "
            "mound of loose earth lie beside the hole."
        ),
        pose=(
            "Jack kneels on one knee in the dirt, leaning forward over the hole, then looking up "
            "toward the viewer with a hopeful, curious smile."
        ),
        camera=(
            "Medium close shot from slightly above, at Jack's eye level. Jack's head and "
            "shoulders fill the upper half of the frame; hands, bean and hole fill the lower "
            "half. The face is large, sharp and fully visible."
        ),
        lighting="Warm, soft golden-hour sunrise light on Jack's face; gentle shadows.",
        avoid=(
            "No beanstalk, sprout, vine or plant growing from the hole yet. No giant, castle "
            "or clouds. No other people. Not standing, not throwing the beans."
        ),
    ),
    SCENES[1]: SceneBrief(
        action=(
            "Jack is climbing the giant magic beanstalk: hauling upward hand over hand, one "
            "hand reaching up to grip the stalk above, one foot braced on a huge leaf below."
        ),
        setting=(
            "Very high in the sky, partway up the beanstalk, among soft white clouds. Far, far "
            "below, through a gap in the clouds, the tiny thatched cottage and patchwork fields "
            "are visible, showing how high Jack has climbed."
        ),
        props=(
            "The beanstalk is gigantic: a trunk-thick, twisting bright green stalk rising out of "
            "the top of the frame, with enormous heart-shaped leaves and curling tendrils. "
            "Jack's hands are wrapped around the stalk."
        ),
        pose=(
            "Jack clings to the stalk mid-climb, body pressed close to it, and looks back over "
            "the shoulder toward the viewer with an excited, slightly breathless grin."
        ),
        camera=(
            "Medium close shot from just beside the beanstalk, level with Jack's face. Jack's "
            "head, shoulders and both hands on the stalk fill most of the frame; the clouds and "
            "the tiny ground far below show in the background and bottom corner. The face is "
            "large, sharp and fully visible, not seen from behind."
        ),
        lighting="Bright, airy high-altitude sunlight; clouds glowing white and gold.",
        avoid=(
            "Jack is not standing on the ground, not planting, and not at the top. No giant, "
            "castle, golden goose or harp. No other people. Not a small plant: the beanstalk "
            "is enormous."
        ),
    ),
}

# Each style also says how to draw the FACE in that style, so the face never looks like a
# photo pasted onto a cartoon body.
STYLES = {
    "storybook": (
        "classic children's storybook illustration, soft watercolor and ink",
        "painted in the same soft watercolor washes and ink lines as the rest of the picture",
    ),
    "animated3d": (
        "modern 3D animated family-movie style, soft lighting",
        "fully rendered as a 3D animated-film character face: smooth stylized skin, slightly "
        "enlarged expressive eyes, simplified features, the same soft shading and lighting as "
        "the body; never photographic skin texture",
    ),
    "comic": (
        "bold comic-book style with clean ink outlines and flat colors",
        "drawn with the same bold ink outlines and flat colors as the rest of the picture",
    ),
    "papercut": (
        "layered paper-cutout collage style",
        "built from the same cut-paper shapes and textures as the rest of the picture",
    ),
}

# Every level is a real cartoon; the photo is never reproduced. Higher = more exaggerated.
STRENGTH = {
    1: "a gently stylized cartoon: simplified features, clean drawn shapes, painted rather "
       "than photographic skin, close to real head proportions",
    2: "a clear cartoon character: simplified, rounded features, slightly larger head and eyes, "
       "drawn outlines or painted shapes, no realistic skin texture, pores or photo lighting",
    3: "a fully cartoon character, like an animated TV show: big expressive eyes, bold "
       "exaggerated simplified features, big head and small body, bold simple shapes",
}

# Jack for boys, Jane for girls. The scenes above are written for Jack; cast() swaps the name.
HEROES = ("jack", "jane")

NO_TEXT = ("A wordless, full-bleed illustration: no text, letters, title, caption, banner or "
           "border anywhere in the image.")


def cast(text: str, hero: str) -> str:
    return text.replace("Jack", "Jane") if hero == "jane" else text


def _style(style: str, strength: int) -> str:
    style_text, face_style = STYLES.get(style, STYLES["storybook"])
    return (f"STYLE: {style_text}. The character is {STRENGTH.get(strength, STRENGTH[2])}. The "
            f"face is {face_style}. Nothing in the picture may look like a photograph.")


def build_portrait_prompt(style: str, strength: int, face_description: str = "",
                          with_closeup: bool = False, hero: str = "jack") -> str:
    """Step 1: turn the photo into a cartoon character. The scenes are drawn from this, not the photo."""
    refs = ("The reference photos (image 1 the full photo, image 2 a close-up of the face) are "
            "only a guide") if with_closeup else "The reference photo is only a guide"
    described = f" Their distinctive features: {face_description}." if face_description else ""
    return "\n".join([
        f"Create a brand-new cartoon character portrait of the person in the photo, to be "
        f"{cast('Jack', hero)} in a Jack and the Beanstalk picture book. {refs}: do not edit, "
        "trace or filter the photo. Redraw the person from scratch as a cartoon.",
        "LIKENESS: Keep what makes them recognizable, the way a good caricaturist does: their "
        "hairstyle and hair color, skin tone, face shape, the character of their eyes, nose, "
        "brows and smile, their apparent age and gender, and any glasses or facial hair. Simplify "
        "everything else." + described,
        _style(style, strength),
        "FRAMING: Head and shoulders, facing the viewer with a friendly smile, wearing a simple "
        "patched linen peasant tunic, on a plain soft pastel background.",
        NO_TEXT,
    ])


def build_prompt(scene: str, style: str, strength: int, hero: str = "jack") -> str:
    """Step 2: put the cartoon character from step 1 into a scene."""
    brief = SCENE_BRIEFS[scene]
    name = cast("Jack", hero)
    return "\n".join([
        f"CHARACTER: The reference image is the cartoon character {name}. Draw exactly this "
        "character: the same face, hairstyle, hair color, skin tone, glasses or facial hair, "
        "proportions and drawing style. Do not make them more realistic.",
        _style(style, strength) + " " + NO_TEXT,
        # The caption is added by the app outside the image, so it is phrased as a moment, not a caption.
        f"SCENE from the fairy tale Jack and the Beanstalk, with {name} as the hero. "
        f"Illustrate this moment: {cast(scene, hero)}",
        f"ACTION: {cast(brief.action, hero)}",
        f"SETTING: {cast(brief.setting, hero)}",
        f"PROPS: {cast(brief.props, hero)}",
        "WARDROBE: Simple fairy-tale peasant clothes: a patched linen tunic, brown trousers, "
        "a rope belt, worn leather boots.",
        f"POSE: {cast(brief.pose, hero)}",
        f"CAMERA: {cast(brief.camera, hero)}",
        f"LIGHTING: {brief.lighting}",
        f"AVOID: {cast(brief.avoid, hero)} Never write any words in the picture.",
    ])


DESCRIBE_FACE_PROMPT = (
    "Describe this person's face for a caricature artist who must make it recognizable, in "
    "2-3 short lines: hair (color, length, texture, style, hairline), face shape and jaw, "
    "eyes (shape, size, spacing, color if visible), brows, nose (width, length, shape), lips, "
    "skin tone, approximate age, and any glasses, facial hair, freckles, moles or other "
    "distinctive features. Focus on what makes this face different from an average face. "
    "Facts only, no names or opinions."
)
