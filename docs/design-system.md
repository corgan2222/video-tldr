# Design system

What every surface of this project looks like: the welcome page, the
documentation site, the diagrams, promotional material. The palette is
not invented here — it is read off the banner in
`docs/assets/github-banner-1280x320.png`, so the product and everything
around it agree without anyone matching colours by eye.

## The idea in one line

A technical report, not a product brochure. Dark ground, warm white
text, one violet accent that comes from the play mark. Colour means
something: violet leads, cyan and green separate alternatives, amber and
red warn. Nothing is coloured for decoration.

## Colour

| Role            | Token           | Value                  |
| --------------- | --------------- | ---------------------- |
| Ground          | `--ground`      | `#0F0F16`              |
| Surface         | `--surface`     | `#16161F`              |
| Surface, raised | `--surface-2`   | `#1E1E2A`              |
| Text            | `--ink`         | `#EDEDF2`              |
| Text, secondary | `--ink-2`       | `#A8A8B8`              |
| Text, tertiary  | `--ink-3`       | `#6E6E80`              |
| Rule            | `--line`        | `#2A2A38`              |
| Accent          | `--violet`      | `#7C5CFF`              |
| Accent, lifted  | `--violet-soft` | `#9B85FF`              |
| Accent, ground  | `--violet-bg`   | `#1A1630`              |
| Second tone     | `--cyan`        | `#4CC9F0` on `#10222C` |
| Third tone      | `--green`       | `#4ADE80` on `#102318` |
| Warning         | `--warn`        | `#D6A159` on `#2E2312` |
| Error           | `--bad`         | `#E08A83` on `#331B19` |

The red of the play mark, `#E8332A`, belongs to the logo. It is not a UI
colour: used for anything else it reads as an error.

Three tones — violet, cyan, green — are exactly enough to tell parallel
options apart. A fourth starts to look like a chart.

## Type

- Text: `"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial`
- Mono: `ui-monospace, "Cascadia Mono", Consolas, "SF Mono"`
- Base 15.5px, line height 1.62, running text at most 68 characters wide
- Headings: weight 700, letter-spacing `-0.022em`, always
  `text-wrap: balance` — without it a sentence breaks mid-clause
- Eyebrow labels: mono, 0.72rem, uppercase, letter-spacing `0.14em`
- Numbers to be compared: mono with `font-variant-numeric: tabular-nums`,
  so they do not jitter while counting

## Parts

**Card.** Surface ground, 1px rule, a 3px top border in the card's tone,
10px radius. Number and badge share the first line; the title gets its
own, because a title that wraps beside a number leaves it crooked.

**Badge.** Mono, 0.62rem, uppercase, the tone on its own dim ground. It
says what the option costs, not what it is: `easiest`, `needs PyPI`,
`works today`.

**Command block.** Ground inside a surface, mono at 0.79rem, a `$` in the
tone before it. **It wraps, it does not scroll.** A horizontal scrollbar
inside a card reads as a defect, and a command that gets copied does not
need to be one line. The copy control is a 28px icon button at the top
right, inside — two overlapping sheets, the sign every editor uses. It
carries `title` and `aria-label`, because an icon alone says nothing to a
screen reader.

**Cards in a row share their rows.** The grid declares
`grid-template-rows: auto auto 1fr auto` and each card takes
`grid-row: span 4` with `grid-template-rows: subgrid`. Title, text and
command block then sit on one line across all of them, however long the
text above happens to be. Without it each card stacks on its own and the
command blocks start at three different heights.

**Inline code.** Violet on `--violet-bg` with a 1px border, `nowrap`.
Every command, path, port and address in running text gets it — prose and
things you type must be distinguishable at a glance.

**Key caps.** Mono in `--surface-2`, bottom border 2px so it reads as a
key. For things the reader presses: `Win`, `Enter`.

**Section break.** A form's sections are separated, not titled: 32px of
air and a 1px rule, nothing else. A heading over a field label said the
same thing twice — "Summary" above "Language of the summary" — and two
labels of different sizes above one field is one label too many.

**Field label.** Small caps, 10.5px, letter-spacing `0.1em`, in
`--violet-soft`. A label is metadata, not content: at the size, weight
and colour of the value beneath it, the two read as one block and nobody
can tell the question from the answer. Violet is what marks a label
everywhere else here, so anything standing over a line of its own carries
it. Labels beside a checkbox are the exception — there the text _is_ the
value, so it keeps the text size and the text colour.

**Two levels, told apart by colour.** Label and value. Where the label
loses its own section heading, it takes over what that heading said:
`Blocked hosts` becomes `Open all links: blocked hosts`.

**Callout.** Surface with a 3px left border in the tone. For the one
thing that follows from everything above it.

**Advanced lid.** A `details` whose summary is one line on a surface, a
violet triangle in front, sentence case — a switch, not a heading. What
goes behind it is every field a fresh install leaves empty: none of them
is needed for a first run, and a page of empty fields reads as a page of
work. **It opens itself whenever one of those fields carries a value.** A
setting nobody can find again is worse than a field nobody needs.

**Primary button.** Violet fill, white text, 8px radius, an arrow after
the label. At most one per screen: it is the way onward, and a second one
beside it makes both a question.

## Motion, and what it says

Pointing at one of several parallel options dims the others to 40%,
140ms. That is the whole animation budget. It carries meaning: these are
alternatives, not steps. Where things really are steps, they are
numbered and nothing dims.

## Rules that are not decoration

- **One colour per meaning.** If violet leads, nothing else leads.
- **No gradient, no shadow, no radius above 10px.**
- **Never repeat what the banner already says.** If the banner carries
  the name and the tagline, the page below does not say them again.
- **A number on screen carries a unit and, where it was measured, a
  date.**
- **Dark is the design, not a mode.** Every surface, whatever the system
  asks for — the welcome page, the settings, the popup. Half a product in
  light mode beside a dark banner reads as two products. There is no
  light theme to keep in step either, which is one palette fewer to
  maintain.
- **`accent-color` on the root.** Checkboxes, radios and progress bars
  paint themselves; without it they arrive in the system blue, which
  belongs to somebody else's palette.

## Borrowed marks

The store badges in `website/public/badges/` are Mozilla's and Google's,
downloaded from their own branding pages. They are the one place where
this palette does not apply: **resize them, change nothing else.** Both
vendors require the badge to link to a listing that exists, and Google
requires it to disappear whenever the extension is not in the store —
which is why they render off an address that is empty until then.

## Where this is implemented

|                        |                                                         |
| ---------------------- | ------------------------------------------------------- |
| `src/welcome.html`     | the reference: palette, cards, command blocks, key caps |
| `docs/diagrams/*.html` | archify at its `editorial` preset, same tone            |
| `website/`             | the documentation site                                  |
| `src/ui.css`           | popup and settings, the same palette                    |
