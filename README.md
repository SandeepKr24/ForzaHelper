# ForzaHelper

Car search and comparison for Forza Horizon 6. Browse and filter a roster of 635 cars (I am updating the carlist regularly) on their stock specifications, compare up to four side by side, or describe what you want in plain English and let the Car Finder pick the suggestions for you.

## Features

* **Explorer.** Filter by make, model, class, PI, drivetrain, country, year, price, power, torque and weight. Every column is sortable, and the view can be shared as a URL.
* **Car Finder.** Type a request such as "AWD cars around 500 hp under 100k" and it is turned into structured filters. Follow-up messages refine the current search instead of starting over.
* **Compare.** Put up to four cars side by side. Differences are marked.
* **Car detail.** The full specification for a single car. Access by clicking the row.
* **Units.** Switch between imperial(Freedom) and metric(Normal) without another request to the server. A joke, I do not intend to insult anyone.
* **Light and dark themes**, and a layout that works on phones (android and ios both).

## How it works

The language model interprets requests. PostgreSQL answers them.

```
message -> model extraction -> validation -> tolerance policy
        -> query builder -> PostgreSQL -> ranked results
```

The model never writes SQL, never sees database credentials and never decides which cars match. It turns a message into a validated filter object, and a deterministic query builder turns that into parameterised SQL. Column and sort names come from fixed whitelists, and every user value is a bound parameter.

A few rules the search follows:

* **"Around 450 hp" is a range, not an exact match.** It expands to plus or minus 10%, and the range used is always reported back.
* **Vague words get no invented numbers.** "Cheap" or "fast" applies no filter. The response asks what you meant instead.
* **Missing data is excluded, and says so.** A car with no torque figure never matches a torque filter, and the response states how many cars were dropped for that reason.
* **Nothing is silently ignored.** A request the data cannot satisfy, such as a country with no cars, returns no results along with the reason, rather than a list that looks right but is not.
* **No silent relaxation.** An empty search returns alternatives, each changing exactly one constraint, with a threshold the database has confirmed will produce results.
* **Accent-insensitive search.** "Huracan" finds "Huracán".

If no model is configured, or the model fails or returns something invalid, a rule-based extractor takes over. The whole app works without an API key.

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.13, FastAPI, Pydantic |
| Database | PostgreSQL on Supabase, accessed with psycopg |
| LLM | Anthropic, through LangChain |
| Frontend | Single-page HTML and JavaScript, served by the backend |
| Hosting | Vercel |

FastAPI serves both the API and the frontend from one deployment, so everything is on a single origin. The browser only talks to the API and never touches the database.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
uv sync
cp .env.example .env    # fill in the database and model settings
uv run forzahelper      # http://127.0.0.1:8000
```

The app is at <http://127.0.0.1:8000> and interactive API docs are at <http://127.0.0.1:8000/docs>.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `host`, `port`, `database`, `user`, `password` | Supabase Postgres connection |
| `FH_DATABASE_URL` | A single connection URL instead of the five keys above |
| `FH_LLM_PROVIDER`, `FH_LLM_MODEL`, `FH_LLM_API_KEY` | Model for the Car Finder. Leave `FH_LLM_MODEL` empty to use the rule-based extractor |
| `FH_ALLOWED_ORIGINS` | CORS origins, only needed if the frontend is served from somewhere else |
| `FH_ENVIRONMENT` | `development` enables auto-reload |

When deploying, set these in the hosting provider. `.env` is not deployed.

### Database

Run the SQL files in [`db/`](db/) once, in order:

| File | Purpose |
| --- | --- |
| `01_fix_encoding.sql` | Repairs 28 rows whose accented characters were corrupted on import |
| `02_cars_api_view.sql` | Creates the `cars_api` view: clean column names, numeric prices, stable ids |
| `03_optional_unaccent_ids.sql` | Optional, nicer ids for cars with accented names |

The app only reads from `cars_api`. The underlying table is never written to.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness and database reachability |
| GET | `/api/metadata` | Car count, data source and tolerance policy |
| GET | `/api/filters` | Available filter values and numeric bounds, read from the data |
| GET | `/api/cars` | Paginated browsing with query-parameter filters |
| GET | `/api/cars/{id}` | A single car |
| POST | `/api/cars/search` | Structured search |
| POST | `/api/compare` | Side-by-side comparison |
| POST | `/api/chat` | Conversational search for the Car Finder |

Errors always have the same shape and never expose internals:

```json
{ "error": { "code": "INVALID_FILTER",
             "message": "filters: horsepower_min cannot be greater than horsepower_max" } }
```

## Tests

```bash
uv run pytest
```

The suite covers exact, range and categorical filters, "around" interpretation, missing data, follow-up messages, no-result recovery, malformed model output, and SQL injection attempts against both the query builder and the live database. Database tests are skipped when no database is configured.

Tests never call the model by default, so they are free and deterministic. To test against the real model:

```bash
FH_LIVE_LLM=1 uv run pytest tests/test_llm_live.py -v
```

## Project layout

```
main.py                 entry point for Vercel
src/forzahelper/
  api.py                routes, error handling, serves the frontend
  config.py             settings
  db.py                 connection pool
  models.py             request and response models
  search.py             query builder
  interpret.py          tolerance rules and no-result alternatives
  chat/
    extraction.py       model and rule-based extractors
    orchestrator.py     one conversational turn
db/                     SQL to run against the database
ui/                     the frontend
tests/
```

## Notes on the data

* Stock values only. Upgrades and tunes are not reflected.
* PI class bands are read from the data rather than hard-coded, since they differ from earlier Forza games.
* The year 2554 on the M12S Warthog is correct. It is the Halo car.

## Credits

The frontend was designed with Claude Design. The backend, database, API and search logic were built by Sandeep Kumar.

Forza Horizon is a trademark of Microsoft. This is an unofficial fan project and is not affiliated with or endorsed by Microsoft or Playground Games.
