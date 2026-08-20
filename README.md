# CityGuide Demo

A small Flask website designed for a software-development demo.

## Stack
- Python 3
- Flask
- SQLite
- Jinja2
- Vanilla HTML/CSS/JS

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
python3 src/app.py
```

Git Bash:
```bash
python3 -m venv .venv
source .venv/Scripts/activate
pip install -r src/requirements.txt
python3 src/app.py
```

Open http://127.0.0.1:5000

## Demo scenario

The project contains **3 intentionally hidden bugs**. They are not documented in the UI, so they can be used as debugging tasks.

Suggested feature for implementation:

### "Personal Trip Planner"
Allow a visitor to:
- save places to a personal trip;
- reorder saved places;
- assign a visit date/time;
- show total planned places and an estimated walking distance;
- persist the plan in SQLite.

This is deliberately bigger than a single CRUD screen and gives good opportunities to demonstrate requirements analysis, backend work, database changes, frontend work, and tests.

## Intended hidden bugs

For the demo facilitator only:

1. **Search bug** — the search filter is case-sensitive.
2. **Details bug** — a missing place ID causes an unhandled database lookup result.
3. **Statistics bug** — the homepage statistics count inactive places too.

These are intentionally subtle and should be discovered during testing/debugging.

## Run with Docker Compose

Make sure Docker and Docker Compose are installed, then run:

```bash
docker compose up --build
```

Open http://127.0.0.1:5000

Run in the background:

```bash
docker compose up --build -d
```

Stop it:

```bash
docker compose down
```

The SQLite database is stored in a Docker named volume, so it survives container recreation.

To remove the database as well:

```bash
docker compose down -v
```
