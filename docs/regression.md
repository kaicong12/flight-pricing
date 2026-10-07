# Regression flow

The check to run after any change, in order. Stop at the first failure and fix it before going on.

## 1. Static gate — always

```
make lint     # ruff + eslint + tsc
make test     # pytest (migrates a fresh <DATABASE_URL>_test itself) + src/lib/*.check.ts
```

CI (`.github/workflows/backend.yml`) runs only ruff and pytest; nothing but `make` runs the client's
checks.

## 2. Migrations — when `libs/db` changed

```
cd tp_backend
uv run alembic -c libs/db/alembic.ini heads      # exactly one head
uv run alembic -c libs/db/alembic.ini downgrade -1 && uv run alembic -c libs/db/alembic.ini upgrade head
```

## 3. Live walk-through — when a screen or an endpoint changed

`make dev`, then drive `http://localhost:3000` with Playwright. Sign-in is Google OAuth, so a person
signs in once in the Playwright browser; the session cookie then lasts the run.

1. **Create.** A trip on a warm city (Tromsø) with a second city. `/trip/{id}` settles without polling
   forever, and the title reads "Tromsø + …".
2. **Shortlist.** Places load; each category chip filters; the source filter (YouTube / RedNote) narrows
   with a chip still applied; "Show more" pages.
3. **Plan.** Drag a place onto a slot; drag it later; resize both edges (30-minute snap) — the block and
   its neighbours' lanes redraw while held, and the day saves and re-checks only on release. A click on
   any block opens its dialog; a drag never does. The grid runs 00:00–24:00 and the flight hours are hatched.
4. **Custom block.** "+" on a slot, type exact minutes (e.g. 07:13–07:20); it keeps them after a reload.
   Add an overnight one ending on the next day: it draws on both days, its tail opens the dialog, the last
   day's bottom edge resizes it, and a time past the departure is refused.
5. **Check.** The day re-routes and warnings render; a place past its closing time warns.
6. **Costs.** The pencil on the overnight block, a cost and a tag, then the Expenses tab: the cost
   appears once, the donut has the tag, and the currency total moves by exactly that amount.
7. **Export.** `export.xlsx` opens; the overnight block's End reads "Day N HH:MM".
8. **Upload.** Upload that export from `/trips`: the preview lists the days, a new start date shifts
   them, and the new trip opens with the same blocks. A file edited in Excel keeps the edits; any other
   .xlsx is refused.
9. **Share.** Add a viewer; as the viewer, nothing that would 403 is offered.
