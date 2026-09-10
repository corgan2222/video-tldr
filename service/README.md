# corganshelper service

The local service the browser extension talks to. Every pipeline step is a
command line entry point that runs the same code the HTTP service runs;
`run` chains them, `serve` offers them to the extension.

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
uv run corganshelper run https://youtu.be/BT4ywlPr6Pk          # all of the above
uv run corganshelper run --batch urls.txt                      # one URL per line
uv run corganshelper serve                                     # for the extension
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

`run` walks every step for one video and prints what each cost: the
seconds per step, the pictures kept, the tokens spent, the files written.
The note is rendered once right after `analyze`, so a video that fails in
`frames` still has a summary. A step that already has its result is
skipped; `--force` redoes them all. `run --batch FILE` takes one URL per
line and prints a Markdown table, one row per video, as each finishes.

## Serving the extension

`corganshelper serve` listens on `http://127.0.0.1:8765` (`--port`
changes that) and prints a token; paste both into the extension's
options. The extension hands over the URL of the active tab, the service
runs `run` on it, one job at a time, and the extension polls the job
until it is done. A click on the notification asks the service to open
the result: the note in Obsidian when that format was written, else the
first document among PDF, Word and Markdown.

| Request                     | Answer                                                            |
| --------------------------- | ----------------------------------------------------------------- |
| `POST /jobs {"url": ...}`   | `202` and the job; `400` when the URL is no YouTube video         |
| `GET /jobs/<id>`            | the job: `status` (queued, running, done, error), `step`, results |
| `POST /jobs/<id>/open`      | `{"opened": ...}`; `409` until the job is done                    |
| `GET /config`               | the settings (secrets masked) and the choices for each of them    |
| `PUT /config {key: value}`  | writes the keys given to `config.json`, answers like `GET`        |
| `GET /models?llm=<backend>` | the names that backend accepts as `model`; `400` with the reason  |

Every request must carry `Authorization: Bearer <token>` and a `Host`
header of `127.0.0.1:<port>`; an `Origin` header is accepted only from
`moz-extension://` and `chrome-extension://`. The service sends no CORS
headers, so a web page cannot reach it. The token lives in `config.json`
as `token`; delete it there to have `serve` make a new one.

What the service did is in `serve.log` next to the data (three files of
a megabyte, the newest without a number): every request with its status,
every job with its steps, every failure with its traceback. The
extension's side is in the console of its background script:
`about:debugging`, This Firefox, Inspect next to corganshelper.

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
| `token`                                         | what the extension sends with every request                                                                                           | made up by `serve` when empty and printed once                                                                                                                              |

`probe` says what keeps the chosen backend from answering. A local model
needs a context window that holds the transcript and its own thinking;
load it with 32768 tokens or more.

Data lives under `CORGANSHELPER_HOME` (default `D:/corganshelper`): `work/<id>/`
holds the per-video results, `models/` the downloaded speech models, `out/`
the rendered documents. Set `CORGANSHELPER_COOKIES` to a cookies file only
when YouTube answers with a sign-in check; the yt-dlp wiki explains the
export and warns that an account used this way can be locked.

Checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`.
