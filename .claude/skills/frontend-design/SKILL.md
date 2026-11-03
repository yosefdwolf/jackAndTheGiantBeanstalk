---
name: frontend-design
description: Design rules for this app's pages (static/index.html, styles.css, app.js, the per-story theme folders in static/themes/, and the review, results and debug pages). The site makes children's picture books, so it should be playful and themed to each story, while avoiding the generic AI-template look. Use whenever creating or changing anything visual in this project: layout, colors, type, components, progress UI, the flip-book viewer, empty and error states. Also use when asked to "make it look better", "more fun", "less generic" or "less like AI".
---

# Frontend design: picture books for children

This site makes picture books starring a child, so it should feel like **opening a picture book**:
playful, illustrated and full of the story's world. Every story gets its own theme. Jack and the
Beanstalk has sky, clouds, a beanstalk, magic beans and a giant's castle in the clouds. A new story
brings its own world. It's for parents and children, so it should feel warm and delightful, never like
a SaaS form with a fairy-tale color swap.

Read the current page and its theme before changing anything. Change the system (theme tokens,
components) rather than restyling one-off elements.

## Themes are per story

- Each story has a theme folder `static/themes/<story>/` with `theme.css` (tokens and scenery) and its
  scenery markup. The story file names its theme (`theme:` in `stories/*.yaml`). A new story is a new
  folder, with no edits to shared CSS.
- Shared components (`styles.css`) use only theme tokens: `--sky`, `--sky-deep`, `--ground`,
  `--leaf`, `--leaf-deep`, `--accent` (the story's magic color), `--card`, `--ink`, `--ink-soft`,
  `--alert`, plus `--display`, `--hand` and `--text` fonts.
- Jack and the Beanstalk: a soft daytime sky, rolling green hills, a cottage, a beanstalk curling up the
  side, drifting clouds, and magic-bean gold (`--accent`). Dark mode is the same scene at night: deep
  blue sky, stars, lamplit cottage windows. It's the same world, not inverted greys.

## Make it fun

- **Illustrated scenery, drawn in SVG,** is the decoration: hills, clouds, the beanstalk, beans, the
  cottage, a castle peeking from the clouds. Gentle motion (a cloud drifting, a leaf swaying) is fine
  if it's slow, sparse and respects `prefers-reduced-motion`.
- **Content sits on "pages":** cream cards with a slightly irregular hand-drawn edge or a soft paper
  shadow, like pages laid on the scene. Rounded corners are fine here (8–16px), because this is a
  storybook.
- **Type with personality, but readable:**
  - Display: **Grandstander** (bouncy, hand-lettered) for titles.
  - Handwritten notes and labels: **Shantell Sans**.
  - Reading text: **Literata**.
  - Avoid Fredoka, Baloo, Poppins and Inter. They're the overused "friendly AI app" picks.
- **The finished book is a flip book** that you turn page by page on the site, with the story text set
  on the art just like in the PDF. The PDF is the download.
- **Progress tells the story.** Each picture has its own row and bar, and the beanstalk grows as
  pictures finish. Each row says what's being drawn ("Sketching Jane and the others").
- **Copy** is warm and specific to the story, like a picture-book narrator. "Pop in the magic word"
  beats "Enter password". Talk about the child and the story, never "AI-powered".

## Still never (the AI-template tells)

- Emoji as icons (📸 🌱 📖 ✨). Draw small SVG icons in the theme, or use none.
- A generic gradient hero with a centered H1, an italic accent word and a subtitle. Scenery isn't a
  gradient with text on it: it's drawn things.
- "Step 1 / 2 / 3" number-in-a-circle cards. Identical white cards with the same soft shadow everywhere.
- Purple, teal/indigo, or the standard Tailwind palettes. Glassmorphism, blur, neon glow.
- Filler copy: "Unleash", "Seamless", "Effortless", "Bring your story to life", "Magic ✨".

## Components

- **Inputs must look like inputs:** a clear box (2px border, card background, 12px radius), a label
  above, a large tap target, and an obvious focus state. Never just a faint underline (users couldn't
  find the name field).
- **Buttons:** chunky and friendly. Filled with `--leaf` or `--accent`, a 2px darker edge, a slight
  "pressed" drop on click. One primary action per screen.
- **The password gate comes first:** a small friendly card ("the magic word"). Once it's correct it
  disappears and the rest of the page appears. The page remembers it on this device, so returning users
  never see it again unless it changes.
- **Photo upload:** a picture frame or a polaroid inside the scene, with "Pop a photo of your child in
  here".
- **Errors:** a kind note right next to the thing it's about, with the reference in small type. Never
  a toast in a corner.

## Accessibility and mobile (non-negotiable)

- Text contrast is at least 4.5:1 in both themes, including text on scenery (put text on cards, not on
  busy sky).
- Tap targets are at least 44px. Inputs are 16px or larger, so iOS doesn't zoom.
- Works at 375px with no horizontal scroll. Scenery scales down or simplifies on phones.
- Keyboard: a visible focus state on everything. The flip book turns with the arrow keys and buttons,
  not only by swiping.
- Respect `prefers-reduced-motion`. Check browser support for every feature: older iPhone Safari
  matters (see the `AbortSignal.timeout` crash in git history). Any CDN library needs a pinned version
  and a working fallback.

## Before you call it done

1. Screenshot at 375px and 1280px, in light and dark, and look at it.
2. Go through the "still never" list.
3. Ask: would a child smile at it, and could a stranger tell it came from a template?
4. Run `python -m pytest`.
