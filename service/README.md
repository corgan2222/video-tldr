# corganshelper service

The local service the browser extension talks to. Every pipeline step is a
command line entry point that runs the same code the HTTP service will run;
`serve` is the last step to land.

```
cd service
uv sync
uv run corganshelper probe
uv run corganshelper fetch https://www.youtube.com/watch?v=BT4ywlPr6Pk
uv run corganshelper transcribe https://www.youtube.com/watch?v=BT4ywlPr6Pk
```

`transcribe` reads YouTube's own caption track when `fetch` found one and
falls back to faster-whisper otherwise; `--engine whisper` forces it. Whisper
on the GPU needs the CUDA runtime wheels: `uv sync --extra gpu` (about 2 GB).
`CORGANSHELPER_WHISPER` picks the device, `cuda:0` by default, `cuda:1` for
the second card, `cpu` for none.

Data lives under `CORGANSHELPER_HOME` (default `D:/corganshelper`): `work/<id>/`
holds the per-video results, `out/` the rendered documents. Set
`CORGANSHELPER_COOKIES` to a cookies file only when YouTube answers with a
sign-in check; the yt-dlp wiki explains the export and warns that an account
used this way can be locked.

Checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`.
