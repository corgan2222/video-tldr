# Getting into the stores

Everything a submission needs, in the order it is needed. One package
serves all three stores: Firefox reads `background.scripts` and the
`gecko` block, Chromium reads `background.service_worker`, and each
ignores the other. Brave, Opera and Vivaldi install from the Chrome Web
Store and need no submission of their own.

## Before the first submission

|         |                                                                                                                                                                                                                                                                                                                             |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Firefox | [addons.mozilla.org/developers](https://addons.mozilla.org/developers/), free, needs a Mozilla account                                                                                                                                                                                                                      |
| Chrome  | [chrome.google.com/webstore/devconsole](https://chrome.google.com/webstore/devconsole/), 5 USD once. The developer email cannot be changed afterwards.                                                                                                                                                                      |
| Edge    | [partner.microsoft.com/dashboard/microsoftedge](https://partner.microsoft.com/dashboard/microsoftedge/public/login), free. A work or school account is refused; use a personal Microsoft account or sign in with GitHub. Country and account type are read-only after enrolment, and company accounts take weeks to verify. |

Start with Firefox. Its review is the strictest of the three and the only
one that reads the source, so what passes there passes elsewhere, and a
rejection costs nothing.

## What to upload

`npm run build` writes `dist/`, and the release workflow zips it as
`video-tldr-<version>.zip`. That zip is what every store takes. The
manifest must sit at the root of the zip, which it does.

Never upload a zip built by hand from a working tree: it carries whatever
was lying around. Take the one attached to the release.

## The listing

**Name:** video-tldr

**Summary** (Chrome cuts at 132 characters; `tests/manifest.test.ts`
keeps the manifest description inside that, and both say the same thing):

> Watch it. Vault it. One click turns the YouTube video in the active tab
> into a summary with pictures, as a note, PDF or Word file.

**Description:**

> video-tldr turns a YouTube video into something you can read.
>
> Click the toolbar icon on a video and pick Fast or Thorough. A small
> service on your own machine fetches the title, description, chapters
> and captions, transcribes the audio when there are no captions, has a
> language model sort and summarise what was said, pulls still frames at
> the moments worth seeing, reads the commands off those pictures and the
> installation steps out of any linked GitHub repository, and writes the
> result as Markdown, as a note in an Obsidian vault with the video
> embedded, as PDF and as a Word file.
>
> The window shows every step with the seconds it took, a progress bar
> estimated from your earlier runs, the model and the transcriber in use,
> and the service log. A second video queues behind the first, and a run
> can be cancelled.
>
> You choose where the thinking happens: the Claude Code CLI, the
> Anthropic or OpenAI API, or LM Studio and Ollama, which keep everything
> on your machine. The transcriber is Whisper, Parakeet, Canary or
> OpenAI. The settings show what each took on your hardware and let you
> benchmark several against the same video.
>
> There is a second, smaller thing it does: select text, pick "Open all
> links" from the context menu, and every link in the selection opens as
> a tab — YouTube redirects unwrapped, sponsor and affiliate hosts
> skipped, and links you already opened skipped the next time.
>
> The extension needs a companion service on your machine. It is free
> software, it installs with one command, and the extension shows that
> command when it cannot find it.

**Category:** Productivity

**Privacy policy URL:**
`https://corgan2222.github.io/video-tldr/docs/privacy`

**Support / homepage URL:**
`https://github.com/corgan2222/video-tldr`

## Screenshots

One is the minimum, five the maximum; **1280x800** or **640x400**. Take
them at the same size, on a light background, from a real run:

1. The popup on a YouTube video, with the two buttons and the three lights.
2. The popup mid-run: steps, elapsed seconds, progress bar.
3. The finished note in Obsidian, with pictures and timestamps.
4. The settings page: backends, models, the benchmark.
5. The welcome page with the three ways to install the service.

Chrome also takes a promo tile at 440x280 and a marquee at 1400x560.
Both are optional and neither is worth making before the listing is live.

## What the reviewers will ask about

**The host permission.** It is optional, and the extension asks for it on
the first click rather than at install time. It reaches `127.0.0.1` only.
Say so in the notes to the reviewer; it is the one thing that looks
unusual about this extension.

**Chrome's local network access.** Chromium 142 gates requests to
loopback addresses. Whether that gate applies to an extension service
worker is not settled in the documentation — test it on the Chrome build
before submitting there, by clicking the icon and watching the POST to
127.0.0.1 in the service worker's network panel.

**Source code, for AMO only.** Mozilla needs the source of anything
transpiled, and TypeScript counts. Attach the repository at the tag being
submitted, and give these instructions:

> Requirements: Node 22 and npm.
>
>     npm ci
>     npm run build
>
> The result is `dist/`, which is what the uploaded zip contains. The
> build runs `tsc` over `src/*.ts` and copies everything else in `src/`
> unchanged. No bundler, no minifier, no obfuscation. Every dependency
> comes from npm and is pinned in `package-lock.json`.

## PyPI, for the uv route

`uv tool install video-tldr-service` is one of the three ways the welcome
page offers, and it works only once that name exists on PyPI. Nothing
publishes it today: `.github/workflows/release.yml` attaches the wheel to
the GitHub release and stops there.

Either register the name and upload the wheel by hand at the first
release, or add a step to that workflow with a PyPI trusted publisher.
Until one of the two happens, the uv line on the welcome page is a
promise, and the sentence next to it says so.

## The order

1. Publish the GitHub release. The workflow builds the zip, the wheel and
   the two constraints files from the tag.
2. Submit to AMO. Upload the zip, attach the source, paste the build
   instructions, add the privacy URL.
3. While AMO reviews: load the same zip unpacked in Chrome, click the
   icon on a video, confirm the POST to 127.0.0.1 goes through.
4. Submit to the Chrome Web Store, then to Edge with the same zip and the
   same texts.
5. Once a store listing is live, put its link in `README.md` and in the
   website's getting-started page, above the manual install.

## Not in any store

The service. It stays a release download, because a store distributes
browser extensions and this is a Python program with gigabytes of speech
models behind it. winget was considered and does not fit either: it
installs artefacts, and this is a wheel that uv unpacks into an
environment.
