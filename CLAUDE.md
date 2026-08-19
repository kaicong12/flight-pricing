# Conventions

## Comments and docstrings

Keep them minimal. Code should read on its own.

- One or two lines at the top of a file saying what it is.
- One or two lines per function saying what it does.
- Nothing else, unless a line is genuinely non-obvious — a workaround, a surprising API behaviour,
  or a constraint that isn't visible from the code. Then one short comment, not a paragraph.

Do not write: section banners (`# ---- setup ----`), restatements of the code, usage examples in
docstrings, rationale essays, or explanations of design decisions. Those belong in `PLANNING.md`
or the commit message.

## Docs

`PLANNING.md` is the planning reference: decisions, what works, and gotchas that would cost time to
rediscover. Keep it short and prune it when things change — it is not a research log.

## Spikes

Throwaway exploration lives in `spikes/<topic>/`. Secrets stay in the repo-root `.env` (gitignored);
scripts walk up to find it rather than holding their own copy.
