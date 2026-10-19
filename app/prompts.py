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

STYLES = {
    "storybook": "classic children's storybook illustration, soft watercolor and ink",
    "animated3d": "modern 3D animated family-movie style, soft lighting",
    "comic": "bold comic-book style with clean ink outlines and flat colors",
    "papercut": "layered paper-cutout collage style",
}

# Capped on purpose: past "strong", faces stop looking like the person.
STRENGTH = {
    1: "lightly stylized, close to the real proportions",
    2: "clearly cartoon, but with realistic facial proportions",
    3: "strongly stylized cartoon, while keeping the facial features faithful",
}


def build_prompt(scene: str, style: str, strength: int, face_description: str = "",
                 with_closeup: bool = False) -> str:
    brief = SCENE_BRIEFS[scene]
    style_text = STYLES.get(style, STYLES["storybook"])
    strength_text = STRENGTH.get(strength, STRENGTH[2])
    described = f" Their distinctive features: {face_description}." if face_description else ""
    refs = ("the reference photos (image 1 is the full photo; image 2 is a close-up of their "
            "face, so copy the face from image 2)") if with_closeup else "the reference photo"
    return "\n".join([
        f"IDENTITY: This is a portrait of one specific real person, not a generic character. "
        f"The main character, Jack, is the person shown in {refs}. Reproduce their face "
        "faithfully: the same face shape, jawline, chin and cheekbones; the same eye shape, "
        "size and spacing; the same nose width and length; the same lip shape; the same brow "
        "shape, hairline, hairstyle and hair color; the same skin tone, age, and any glasses, "
        "freckles, moles or facial hair. A friend must recognize them instantly. Do not make "
        "them younger, prettier or more generic, and do not change their gender, age or "
        "ethnicity." + described,
        f"STYLE: {style_text}; {strength_text}. The style applies to the whole picture, but the "
        "face must stay faithful to the reference. A wordless, full-bleed illustration: no "
        "text, letters, title, caption, banner or border anywhere in the image.",
        # The caption is added by the app outside the image, so it is phrased as a moment, not a caption.
        f"SCENE from Jack and the Beanstalk. Illustrate this moment: {scene}",
        f"ACTION: {brief.action}",
        f"SETTING: {brief.setting}",
        f"PROPS: {brief.props}",
        "WARDROBE: Simple fairy-tale peasant clothes: a patched linen tunic, brown trousers, "
        "a rope belt, worn leather boots.",
        f"POSE: {brief.pose}",
        f"CAMERA: {brief.camera}",
        f"LIGHTING: {brief.lighting}",
        f"AVOID: {brief.avoid} Never write any words in the picture.",
    ])


DESCRIBE_FACE_PROMPT = (
    "Describe this person's face for a caricature artist who must make it recognizable, in "
    "2-3 short lines: hair (color, length, texture, style, hairline), face shape and jaw, "
    "eyes (shape, size, spacing, color if visible), brows, nose (width, length, shape), lips, "
    "skin tone, approximate age, and any glasses, facial hair, freckles, moles or other "
    "distinctive features. Focus on what makes this face different from an average face. "
    "Facts only, no names or opinions."
)
