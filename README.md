# corganshelper

_[Deutsche Fassung](docs/README_DE.md)_

A Manifest V3 browser extension for Firefox and Chrome, with a local
service that turns a YouTube video into a summary.

## What It Can Do

- **Video summary.** A click on the toolbar icon hands the YouTube video
  in the active tab to a local service. The service fetches title,
  description, chapters and captions, transcribes the audio when there
  are no captions, has a language model sort and summarise the content,
  pulls still frames at the moments worth seeing, reads the installation
  steps out of linked GitHub repositories and writes the result as
  Markdown, as a note in an Obsidian vault, as PDF and as a Word file. The
  language model runs through the Claude Code CLI, the Anthropic or
  OpenAI API, LM Studio or Ollama; the transcriber is Whisper, Parakeet,
  Canary or OpenAI. The choice is made in the extension's options.
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

1. Start the service: `cd service && uv run corganshelper serve`. It
   prints a token.
2. Open the extension's options, enter the service URL and the token,
   press Connect, choose the language, the outputs and the model, Save.
3. Open a YouTube video and click the toolbar icon. The badge shows the
   step the service is on; a notification says when the summary is
   ready, and a click on it opens the note.
4. Without a browser: `uv run corganshelper run <url>` does the same from
   the command line.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

How AI tools are handled is in [AI_POLICY.md](AI_POLICY.md).

## License

[MIT](LICENSE).

## Documentation

The full documentation is at
[https://corgan2222.github.io/corganshelper/](https://corgan2222.github.io/corganshelper/).
