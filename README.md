# video-tldr

<p align="center"><img src="docs/assets/logo-light.png" alt="video-tldr" width="320"></p>

**Watch it. Vault it.**

_[Deutsche Fassung](docs/README_DE.md)_

Too long to read? A Firefox and Chrome extension with a local service that
turns the YouTube video in the active tab into a summary with pictures.

## What It Can Do

- **Video summary.** The toolbar icon opens a small window with two
  buttons. Fast and Thorough hand the video to a local service, which
  fetches title, description, chapters and captions, transcribes the
  audio when there are no captions, has a language model sort and
  summarise the content, pulls still frames at the moments worth seeing,
  reads the commands off those pictures and the installation steps out of
  linked GitHub repositories, and writes the result as Markdown, as a note
  in an Obsidian vault with the video embedded, as PDF and as a Word file.
- **What the window shows.** Every step with the seconds it took, a
  progress bar and an estimate from your earlier runs, the model and the
  transcriber, the service log, and buttons that open the note in
  Obsidian or the download folder. A second video queues behind the
  first, and a run can be cancelled. Three lights say whether the
  service, the model and the transcriber are ready before you click.
- **Switches per run.** Timestamps into the video, the core message as a
  two-minute read, and deleting the work files afterwards. The wording
  of the note is a choice of its own: plain, terse, no marketing words,
  technical, conversational, or all of them at once for comparing.
- **Where it runs.** The language model runs through the Claude Code CLI,
  the Anthropic or OpenAI API, LM Studio or Ollama; the transcriber is
  Whisper, Parakeet, Canary or OpenAI. The settings show what each model
  took on your machine and let you benchmark several against the same
  video.
- **Open all links.** Select text, pick "Open all links" from the context
  menu, and every link inside the selection opens as a tab in a new
  window: YouTube redirects unwrapped, sponsor and affiliate hosts
  skipped, links opened once skipped the next time.

## Install

Two parts: the service, and the extension that talks to it.

The service comes from a release. It needs [uv](https://docs.astral.sh/uv/),
which carries the Python with it. Three ways, whichever suits you:

```
irm https://raw.githubusercontent.com/corgan2222/video-tldr/main/install.ps1 | iex
uv tool install video-tldr
git clone https://github.com/corgan2222/video-tldr.git
```

The script picks the right extra for the machine and puts the command on
your PATH. `uv tool install` is shorter if you already have uv. The clone
is what works before any release exists, and what a contributor wants
anyway.

That picks the CUDA libraries when the machine has a card and the ONNX
runtime alone when it has none, puts `video-tldr` on your PATH, and
registers no autostart. You start the service yourself with
`video-tldr serve`; whenever it is not answering, the extension shows
that command with a button that copies it. Add `-Autostart` and a task
starts it at every logon instead — `video-tldr autostart on|off|status`
switches that later, without reinstalling. `-Root D:\video-tldr` keeps
the program, its environment and its data under one directory instead of
three standard places. The speech models download on first use, several
gigabytes of them.

The extension is the `.zip` on the same release: load it as a temporary
add-on in Firefox (`about:debugging`, "This Firefox") or unpack it and
load the folder in Chrome (`chrome://extensions`, developer mode).

Until the first release is published, build both from source. The
extension:

```
npm ci
npm run build
```

Then load `dist/`. The service is in [`service/`](service/README.md);
that README covers its setup and the model choice.

## Usage

1. Start the service: `video-tldr serve`. From a source build:
   `uv run --project service video-tldr serve`.
2. Click the toolbar icon, open Settings, press Connect, choose the
   language, the outputs and the model, Save. A token is needed only
   when the service was given one.
3. Open a YouTube video, click the icon, press Fast or Thorough. The
   window shows the steps as they run; a notification says when the
   summary is ready, and a click on it opens the note.
4. Without a browser: `video-tldr run <url>` does the same from the
   command line.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

How AI tools are handled is in [AI_POLICY.md](AI_POLICY.md).

## License

[MIT](LICENSE).

## Documentation

The full documentation is at
[https://corgan2222.github.io/video-tldr/](https://corgan2222.github.io/video-tldr/).
