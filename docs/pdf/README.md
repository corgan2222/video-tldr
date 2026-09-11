# How the PDF looks

The PDF comes out in the built-in look unless `pdf_template` says
otherwise. Three looks ship with the service, and each answers to its
name — no path, no checkout:

| Name      | For                                                                    |
| --------- | ---------------------------------------------------------------------- |
| `dark`    | The product's own palette. What the extension and the site look like.  |
| `paper`   | Light ground, a serif for the text. For printing and reading on paper. |
| `compact` | Small and tight, pictures capped. A long video on few pages.           |

The same note came out on two pages as `dark` and `paper`, and on one as
`compact` (measured 2026-09-11, with one picture and two command blocks).

## Picking one

For every video from now on, in the settings page under "Design template
for the PDF", or by command:

```bash
video-tldr config --set pdf_template=dark
```

For one video, without changing the setting:

```bash
VIDEO_TLDR_PDF_TEMPLATE=compact video-tldr run <url>
```

Back to the built-in look:

```bash
video-tldr config --set pdf_template=
```

## A look of your own

`pdf_template` takes a path as well, and the suffix decides what happens
with it.

**A `.css` file follows the built-in rules**, so it only has to name what
should differ. This is the short way: copy one of the three out of
`assets/pdf/` inside the installed service, or out of this repository
under `service/src/video_tldr_service/assets/pdf/`, and edit it.

**A `.html` file replaces the page.** It needs `{{content}}` where the
note goes, and may carry `{{title}}`. Nothing of the built-in look
survives, which is the point of it.

### What the note is made of

The PDF is the note's Markdown turned into HTML, so these are the
elements a stylesheet has to reckon with, in the order they appear:

| Element                    | What it is                            |
| -------------------------- | ------------------------------------- |
| `body > p:first-child img` | The video's thumbnail                 |
| `h1`                       | The title                             |
| `h1 + p`                   | Channel, date, length, link, kind     |
| `h2`                       | Summary, sections, key points, links  |
| `h3`                       | One moment, its timestamp as the link |
| `img`                      | A still frame                         |
| `p > em:only-child`        | The caption under that frame          |
| `pre code`                 | Commands read off the picture         |
| `ul`, `ol`, `table`        | Key points, installation steps, links |

### The one rule that is not decoration

```css
html {
  print-color-adjust: exact;
  -webkit-print-color-adjust: exact;
}
```

Chrome prints no background colour unless the page asks for it. Without
those two lines a dark stylesheet arrives as dark text on white paper,
and the tinted code blocks vanish. `tests/test_documents.py` checks that
every look which ships carries the line.

For a page that is dark to the edge, `@page { margin: 0 }` and the
padding on the body: the page margin sits outside the body, and the
ground would stop at it and leave a white frame.
