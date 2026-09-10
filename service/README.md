# The video-tldr service

The local service the video-tldr extension talks to; the package and the repository keep the name corganshelper. Every pipeline step is a
command line entry point that runs the same code the HTTP service runs;
`run` chains them, `serve` offers them to the extension.

```
cd service
uv sync --extra gpu          # or --extra cpu on a machine without CUDA
uv run video-tldr probe
uv run video-tldr fetch https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr transcribe https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr analyze https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr enrich https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr frames https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr render https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run video-tldr render --format obsidian --format pdf https://youtu.be/BT4ywlPr6Pk
uv run video-tldr run https://youtu.be/BT4ywlPr6Pk          # all of the above
uv run video-tldr run --batch urls.txt                      # one URL per line
uv run video-tldr serve                                     # for the extension
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

`video-tldr serve` listens on `http://127.0.0.1:8765` (`--port`
changes that). The extension hands over the URL of the active tab, the service
runs `run` on it, one job at a time, and the extension polls the job
until it is done. A click on the notification asks the service to open
the result: the note in Obsidian when that format was written, else the
first document among PDF, Word and Markdown.

| Request                                    | Answer                                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------------- |
| `POST /jobs {"url", "profile", "options"}` | `202` and the job; `400` on a wrong URL, profile or option                   |
| `GET /jobs/<id>`                           | the job: `status` (queued, running, done, error, cancelled), `step`, results |
| `POST /jobs/<id>/cancel`                   | the job as cancelled; `409` once it has finished                             |
| `POST /jobs/<id>/open {"what"}`            | `{"opened": ...}`; `what` is `obsidian`, `folder` or `auto`                  |
| `POST /bench {"url", "models"}`            | a benchmark job; `GET /bench` returns every row measured so far              |
| `GET /config`                              | the settings (secrets masked) and the choices for each of them               |
| `PUT /config {key: value}`                 | writes the keys given to `config.json`, answers like `GET`                   |
| `GET /models?llm=<backend>`                | the names that backend accepts as `model`; `400` with the reason             |
| `GET /health`                              | four lights: service, language model, transcriber, model abilities           |
| `GET /stats`                               | what earlier runs took, per step, model and transcriber                      |
| `GET /log?lines=<n>`                       | the tail of `serve.log`                                                      |
| `POST /pick {"kind"}`                      | a file or folder dialog on this desktop, for the options page                |

`options` carries what the popup offers per run and overrides the stored
settings for that job: `timestamps`, `condensed`, `cleanup` (each `on`
or `off`) and `style`.

Every request must carry a `Host` header of `127.0.0.1:<port>`; an
`Origin` header is accepted only from `moz-extension://` and
`chrome-extension://`. The service sends no CORS headers, so a web page
cannot reach it. A token is optional: with `token` set in `config.json`
(`video-tldr config --set token=<secret>`), every request must also
carry `Authorization: Bearer <token>`, which keeps other extensions in
the browser out; without one, any extension that may reach 127.0.0.1 can
use the service.

What the service did is in `serve.log` next to the data (three files of
a megabyte, the newest without a number): every request with its status,
every job with its steps, every failure with its traceback. The
extension's side is in the console of its background script:
`about:debugging`, This Firefox, Inspect next to video-tldr.

## Choosing the model

`video-tldr config` shows the settings, `video-tldr config --set
key=value` writes them to `config.json` in the data directory. An
environment variable overrides the file, the flags `--llm`, `--model` and
`--stt` override both for one run. Keys stay in that file or in the
environment; the file lives next to the data, outside the repository.

| Setting                                         | Values                                                                                                                             | Notes                                                                                                                                                                       |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm`                                           | `claude` (default), `anthropic`, `openai`, `lmstudio`, `ollama`                                                                    | `claude` runs `claude -p` from the Claude Code CLI on the subscription; the APIs need `anthropic_api_key` or `openai_api_key`; the local servers need `model` set           |
| `model`                                         | a name the backend accepts                                                                                                         | `video-tldr models` lists them; empty means the backend's default                                                                                                           |
| `stt`                                           | `auto` (default), `subtitles`, or a model from `video-tldr models stt`: `whisper`, `whisper-large`, `parakeet`, `canary`, `openai` | `auto` takes YouTube's caption track when there is one, else `whisper`; the list shows each model's speed class, its Open ASR Leaderboard word error rate and its languages |
| `language`                                      | `de`, `en`                                                                                                                         | language of the note                                                                                                                                                        |
| `formats`                                       | comma list of `md`, `obsidian`, `pdf`, `docx`                                                                                      | what `render` writes besides `summary.md`; default `md`                                                                                                                     |
| `obsidian_vault`, `obsidian_folder`             | a path, a folder inside it                                                                                                         | where the Obsidian note goes, pictures under `_bilder` in that folder; default folder `Videos`                                                                              |
| `browser`                                       | path to `chrome.exe` or `msedge.exe`                                                                                               | prints the PDF; empty searches the usual places                                                                                                                             |
| `lmstudio_url`, `ollama_url`, `openai_base_url` | URLs                                                                                                                               | where the OpenAI-protocol servers listen                                                                                                                                    |
| `token`                                         | what the extension sends with every request                                                                                        | optional; without one the Host and Origin checks alone guard the service                                                                                                    |
| `download_dir`                                  | a folder                                                                                                                           | where the outputs go; empty means the user's Downloads folder                                                                                                               |
| `pdf_template`                                  | an HTML file with `{{content}}`, or a CSS file                                                                                     | the look of the PDF; empty means the built-in one                                                                                                                           |
| `style`                                         | `normal` (default), `caveman`, `noslop`, `engineer`, `human`, `all`                                                                | how the note is worded; `all` writes one note per style, for comparing them                                                                                                 |
| `timestamps`                                    | `on` (default), `off`                                                                                                              | link every section, key point and picture to its moment in the video                                                                                                        |
| `condensed`                                     | `on`, `off` (default)                                                                                                              | boil the video down to a two-minute read                                                                                                                                    |
| `cleanup`                                       | `on`, `off` (default)                                                                                                              | delete `work/<id>/` after a run that wrote its outputs, `run.json` kept                                                                                                     |

`probe` says what keeps the chosen backend from answering, and
`GET /health` says it while the extension is open. A local model needs a
context window that holds the transcript and its own thinking; load it
with 32768 tokens or more. LM Studio's own API tells the service what a
model can do before a run: `type` says whether it reads pictures (`vlm`),
`loaded_context_length` how much it holds. A model that takes no images
no longer fails the run, it leaves the pictures unlabelled. Requests to
LM Studio carry `reasoning_effort: "none"`, because the thinking of a
local model was 94 to 97 percent of what it generated for a one-line
caption (measured 2026-09-10).

`bench` compares models on the same video:

```
uv run video-tldr bench https://youtu.be/BT4ywlPr6Pk --models sonnet,opus --repeat 2
```

It analyses the video once per model and run, prints a Markdown table
with seconds, tokens and tokens per second, and appends every row to
`bench.json` next to the data. The extension's settings page offers the
same over `POST /bench`.

Data lives under `CORGANSHELPER_HOME` (default `D:/corganshelper`): `work/<id>/`
holds the per-video results, `models/` the downloaded speech models, `out/`
the rendered documents. Set `CORGANSHELPER_COOKIES` to a cookies file only
when YouTube answers with a sign-in check; the yt-dlp wiki explains the
export and warns that an account used this way can be locked.

Checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`.
