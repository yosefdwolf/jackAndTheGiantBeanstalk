# Adding a story

A story is one file. Copy `little_red_riding_hood.yaml` to `stories/<your_story>.yaml`, rewrite it, and it is in
the library at `/stories/<your-story>`. Nothing else has to change: no code, no pictures, no theme.

Everything the site says about a story comes from its file:

| Section | What it fills |
|---|---|
| `title`, `blurb` | the library card and the story page's title |
| `pronouns` | the boy/girl question on the form and its two buttons (each sets he/she in the text) |
| `hero` | the hero's name in the pictures and the outfit they wear on every page |
| `site` | the story page's words: big heading, button, progress titles, placeholders, PDF name, and `musing`, the little jobs shown while the book is drawn |
| `world`, `characters` | what the pictures look like and who is in them |
| `pages` | the 20 pages: words, where the words go, who's in the picture, the scene, and the line shown while it's drawn |
| `cover_page` | which page becomes each book's cover on the bookshelf |
| `theme`, `library_cover` | optional: see below |
| `draft: true` | optional: only admins see the story, to try it (and check its characters' pictures) before customers can buy it. Delete the line to publish |

**The template.** Every story has 20 painted pages, then an `about_me` page. Page N puts its words in the same place
in every story (`text_zone`, listed in `TEMPLATE_ZONES` in `app/book/story.py`). A file that doesn't fit is left out
of the library, and the server log says why. `python -m pytest tests/test_new_story.py` checks every file.

**Character pictures.** The first real book of a new story draws each character's reference picture from its
`characters` description (about 4 cents each, while the child's cartoon is being drawn) and saves it in the
database as `<character>-1`; every later book reuses it. Nothing is ever replaced: change a description and the next
book draws `<character>-2`, keeping the old one. To always use one version, add `picture: wolf-1` under that
character (the admin site's Characters tab shows every version; click a name to copy it). A picture you made
yourself can go at `assets/characters/<story>/<key>.png`; it's imported into the database on the next deploy.

**The database mirrors the files.** On every startup the site copies each story file into the `stories` and
`characters` tables (pictures are in `character_pictures`). Never edit those tables: the files win on the next
restart. A story whose file is deleted stays in the database, inactive, so books already made still open.

**Optional extras.**
- `theme`: a folder `static/themes/<theme>/` with `theme.css` and `scene.html` gives the story page its own look.
  Without one, it uses the library's.
- A cover: `static/themes/<theme>/art/cover.webp` (or `library_cover:` pointing anywhere). Without one, the library
  shows a plain book with the title.

**Before you pay for pictures,** read every prompt the story will send:
`python -m scripts.show_prompts <story>` writes them to `docs/prompts/<story>.md`.
