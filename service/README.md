# corganshelper service

The local service the browser extension talks to. Every pipeline step is a
command line entry point that runs the same code the HTTP service will run;
`serve` is the last step to land.

```
cd service
uv sync --extra gpu          # or --extra cpu on a machine without CUDA
uv run corganshelper probe
uv run corganshelper fetch https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper transcribe https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper analyze https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper enrich https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper frames https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper render https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper render --format obsidian --format pdf https://youtu.be/BT4ywlPr6Pk
```

`enrich` reads the README of up to three GitHub repositories the
description links to and stores their installation steps. `frames` fetches
a short clip around every moment `analyze` marked, keeps the sharpest
second of each, has the model label the pictures and keeps at most eight,
none of them a speaker. When none of them is a diagram, the model may
draw one as Mermaid, and Chrome renders it to PNG with the Mermaid script
that ships in the package. `render` places all of it into `work/<id>/summary.md`
when they exist; it does not run them. `--format`, or `formats` in the
settings, adds outputs named `YYYY_MM_DD_<title>` after the day of
processing: `md` copies the note and its pictures to `out/`, `obsidian`
writes a note with frontmatter and wikilinks into the vault, `pdf` prints
the note with Chrome or Edge (the HTML stays next to it), `docx` builds a
Word file with the same pictures.

One of the two extras is needed to transcribe: `gpu` brings the CUDA
libraries for faster-whisper and the ONNX runtime for Parakeet (about 2 GB
of wheels), `cpu` the ONNX runtime alone. `CORGANSHELPER_WHISPER` picks the
device for both local models, `cuda:0` by default, `cuda:1` for the second
card, `cpu` for none.

## Choosing the model

`corganshelper config` shows the settings, `corganshelper config --set
key=value` writes them to `config.json` in the data directory. An
environment variable overrides the file, the flags `--llm`, `--model` and
`--stt` override both for one run. Keys stay in that file or in the
environment; the file lives next to the data, outside the repository.

| Setting                                         | Values                                                                                                                                | Notes                                                                                                                                                                       |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm`                                           | `claude` (default), `anthropic`, `openai`, `lmstudio`, `ollama`                                                                       | `claude` runs `claude -p` from the Claude Code CLI on the subscription; the APIs need `anthropic_api_key` or `openai_api_key`; the local servers need `model` set           |
| `model`                                         | a name the backend accepts                                                                                                            | `corganshelper models` lists them; empty means the backend's default                                                                                                        |
| `stt`                                           | `auto` (default), `subtitles`, or a model from `corganshelper models stt`: `whisper`, `whisper-large`, `parakeet`, `canary`, `openai` | `auto` takes YouTube's caption track when there is one, else `whisper`; the list shows each model's speed class, its Open ASR Leaderboard word error rate and its languages |
| `language`                                      | `de`, `en`                                                                                                                            | language of the note                                                                                                                                                        |
| `formats`                                       | comma list of `md`, `obsidian`, `pdf`, `docx`                                                                                         | what `render` writes besides `summary.md`; default `md`                                                                                                                     |
| `obsidian_vault`, `obsidian_folder`             | a path, a folder inside it                                                                                                            | where the Obsidian note goes, pictures under `_bilder` in that folder; default folder `Videos`                                                                              |
| `browser`                                       | path to `chrome.exe` or `msedge.exe`                                                                                                  | prints the PDF; empty searches the usual places                                                                                                                             |
| `lmstudio_url`, `ollama_url`, `openai_base_url` | URLs                                                                                                                                  | where the OpenAI-protocol servers listen                                                                                                                                    |

`probe` says what keeps the chosen backend from answering. A local model
needs a context window that holds the transcript and its own thinking;
load it with 32768 tokens or more.

Data lives under `CORGANSHELPER_HOME` (default `D:/corganshelper`): `work/<id>/`
holds the per-video results, `models/` the downloaded speech models, `out/`
the rendered documents. Set `CORGANSHELPER_COOKIES` to a cookies file only
when YouTube answers with a sign-in check; the yt-dlp wiki explains the
export and warns that an account used this way can be locked.

Checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`.
