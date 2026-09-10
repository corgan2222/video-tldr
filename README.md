# video-tldr

<p align="center"><img src="docs/assets/logo-light.png" alt="video-tldr" width="320"></p>

**Watch it. Vault it.**

_[Deutsche Fassung](docs/README_DE.md)_

Too long to read? A Firefox and Chrome extension with a local service that
turns the YouTube video in the active tab into a summary with pictures.
The repository keeps its old name, corganshelper.

## What It Can Do

- **Video summary.** The toolbar icon opens a small window with two
  buttons. Fast and Thorough hand the video to a local service, which
  fetches title, description, chapters and captions, transcribes the
  audio when there are no captions, has a language model sort and
  summarise the content, pulls still frames at the moments worth seeing,
  reads the installation steps out of linked GitHub repositories and
  writes the result as Markdown, as a note in an Obsidian vault, as PDF
  and as a Word file. The window shows each step with the seconds it
  took, an estimate of what is left from your earlier runs, the service
  log, and a button to open the result. The language model runs through
  the Claude Code CLI, the Anthropic or OpenAI API, LM Studio or Ollama;
  the transcriber is Whisper, Parakeet, Canary or OpenAI. The choice is
  made in the extension's settings, which also show what each model took
  on your machine.
- **Open all links.** Select text, pick "Open all links" from the context
  menu, and every link inside the selection opens as a tab in a new
  window: YouTube redirects unwrapped, sponsor and affiliate hosts
  skipped, links opened once skipped the next time.

## Install

Until the first release is published, build from source:

```
npm ci
npm run build
```

Load `dist/` as a temporary add-on in Firefox (`about:debugging`, "This
Firefox") or as an unpacked extension in Chrome (`chrome://extensions`,
developer mode). The video summary needs the local service from
[`service/`](service/README.md); that README covers its setup and the
model choice.

## Usage

1. Start the service: `cd service && uv run video-tldr serve`.
2. Click the toolbar icon, open Settings, press Connect, choose the
   language, the outputs and the model, Save. A token is needed only
   when the service was given one.
3. Open a YouTube video, click the icon, press Fast or Thorough. The
   window shows the steps as they run; a notification says when the
   summary is ready, and a click on it opens the note.
4. Without a browser: `uv run video-tldr run <url>` does the same from
   the command line.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

How AI tools are handled is in [AI_POLICY.md](AI_POLICY.md).

## License

[MIT](LICENSE).

## Documentation

The full documentation is at
[https://corgan2222.github.io/corganshelper/](https://corgan2222.github.io/corganshelper/).
