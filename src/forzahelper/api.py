"""FastAPI application.

Endpoint contracts follow doc section 22 and the integration doc section 5.
Errors use the single shape from integration doc section 10, and stack traces
are never returned to the client.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, get_settings
from .db import close_pool, fetch_one, get_pool, healthcheck
from .models import (
    CarFilters,
    CarResult,
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
    Sort,
)
from .search import (
    compare_cars,
    filter_metadata,
    get_car,
    models_for_make,
    search_cars,
)

if TYPE_CHECKING:
    from .chat.extraction import ConstraintExtractor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_pool()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="ForzaHelper API",
    version="0.1.0",
    summary="Forza Horizon 6 car search and recommendation backend.",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Surface the first validation problem in the agreed error shape."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body",))
    detail = first.get("msg", "Invalid request.")
    detail = detail.removeprefix("Value error, ")
    message = f"{location}: {detail}" if location else detail
    return _error("INVALID_FILTER", message, 422)


@app.exception_handler(HTTPException)
async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {404: "NOT_FOUND", 429: "RATE_LIMITED", 400: "BAD_REQUEST"}
    return _error(
        codes.get(exc.status_code, "ERROR"), str(exc.detail), exc.status_code
    )


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # Logged in full server-side; the client gets no internals.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return _error("INTERNAL_ERROR", "An unexpected error occurred.", 500)


SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------- health/meta


@app.get("/api/health")
def health() -> dict[str, Any]:
    ok = healthcheck()
    return {
        "status": "ok" if ok else "degraded",
        "database": "up" if ok else "down",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/metadata")
def metadata(settings: SettingsDep) -> dict[str, Any]:
    row = fetch_one(f"SELECT count(*) AS n FROM {settings.cars_relation}")
    return {
        "car_count": int(row["n"]) if row else 0,
        "relation": settings.cars_relation,
        "sources": [
            {
                "name": "Forza Horizon 6 Car List (spreadsheet)",
                "type": "community",
                "note": "Imported into public.cars; see db/DB_CHANGES.md.",
            }
        ],
        "tolerance_policy": {
            "around_pct": settings.default_tolerance_pct,
            "minimum_absolute": settings.min_tolerance_abs,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/filters")
def filters(
    settings: SettingsDep,
    make: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    """Distinct values and numeric bounds, read from the database.

    Pass `make` to narrow the `model` list to one manufacturer, which is what
    the explorer's Model dropdown needs when a Make is chosen.
    """
    metadata = dict(filter_metadata(settings))
    if make:
        categorical = dict(metadata["categorical"])
        categorical["model"] = models_for_make(make, settings)
        metadata["categorical"] = categorical
        metadata["scoped_to_make"] = make
    return metadata


# ---------------------------------------------------------------------- cars


@app.get("/api/cars")
def list_cars(
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    make: Annotated[list[str] | None, Query()] = None,
    country: Annotated[list[str] | None, Query()] = None,
    car_type: Annotated[list[str] | None, Query()] = None,
    drivetrain: Annotated[list[str] | None, Query()] = None,
    pi_class: Annotated[list[str] | None, Query()] = None,
    model: Annotated[list[str] | None, Query()] = None,
    rarity: Annotated[list[str] | None, Query()] = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_max: int | None = None,
    price_min: int | None = None,
    horsepower_min: int | None = None,
    horsepower_max: int | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    sort: str = "relevance",
    direction: str = "asc",
) -> dict[str, Any]:
    """Paginated browse endpoint for the car explorer."""
    try:
        car_filters = CarFilters(
            make=make,
            country=country,
            car_type=car_type,
            drivetrain=drivetrain,
            pi_class=pi_class,
            model=model,
            rarity=rarity,
            year_min=year_min,
            year_max=year_max,
            price_cr_min=price_min,
            price_cr_max=price_max,
            horsepower_min=horsepower_min,
            horsepower_max=horsepower_max,
            query=q,
        )
        sort_spec = Sort(field=sort, direction=direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request = SearchRequest(
        filters=car_filters,
        sort=sort_spec,
        limit=limit,
        offset=(page - 1) * limit,
    )
    response = search_cars(request, settings)
    return {
        "results": [car.model_dump() for car in response.results],
        "pagination": {"page": page, "limit": limit, "total": response.total},
        "warnings": response.warnings,
    }


@app.get("/api/cars/{car_id}", response_model=CarResult)
def read_car(car_id: str, settings: SettingsDep) -> CarResult:
    car = get_car(car_id, settings)
    if car is None:
        raise HTTPException(status_code=404, detail=f"No car with id {car_id!r}.")
    return car


@app.post("/api/cars/search", response_model=SearchResponse)
def search(request: SearchRequest, settings: SettingsDep) -> SearchResponse:
    response = search_cars(request, settings)
    if response.total == 0:
        # Doc section 16: an empty result comes back with labelled alternatives,
        # never with the original constraints silently loosened. find_relaxations
        # calls search_cars directly, so this does not recurse.
        from .interpret import find_relaxations

        response.relaxed_results = find_relaxations(request.filters, request.sort)
    return response


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    car_ids: Annotated[list[str], Field(min_length=2, max_length=6)]


@app.post("/api/compare")
def compare(request: CompareRequest, settings: SettingsDep) -> dict[str, Any]:
    """Side-by-side comparison. Deterministic -- no LLM involved."""
    cars = compare_cars(request.car_ids, settings)
    found = {car.id for car in cars}
    missing = [cid for cid in request.car_ids if cid not in found]
    if not cars:
        raise HTTPException(status_code=404, detail="None of those car ids exist.")
    return {
        "results": [car.model_dump() for car in cars],
        "missing_ids": missing,
        "fields": [
            "price_cr",
            "pi",
            "pi_class",
            "horsepower",
            "torque_lbft",
            "weight_lb",
            "drivetrain",
            "hp_per_tonne",
            "price_per_hp",
        ],
    }


# ---------------------------------------------------------------------- chat


def _extractor_dependency(settings: SettingsDep) -> "ConstraintExtractor":
    """Resolved per request so tests can override it without a live model."""
    from .chat.extraction import get_extractor

    return get_extractor(settings)


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    extractor: Annotated["ConstraintExtractor", Depends(_extractor_dependency)],
) -> ChatResponse:
    from .chat.orchestrator import chat

    return chat(request, extractor=extractor, settings=settings)


# ---------------------------------------------------------------- static site
#
# The frontend is served by this app so that both ship as one deployment and
# share an origin -- which removes CORS from the picture entirely. Mounted last
# because a mount at "/" matches everything, and the API routes above must win.

def _find_ui_dir() -> Path | None:
    """Locate ui/ without assuming the deployed layout.

    Vercel bundles the project and runs with the project root as the working
    directory, but the package may sit at a different depth than in the repo,
    so several candidates are tried rather than one hard-coded path.
    """
    candidates = [
        Path(__file__).resolve().parents[2] / "ui",  # repo layout: src/forzahelper/
        Path.cwd() / "ui",
        Path(__file__).resolve().parents[1] / "ui",
        Path(__file__).resolve().parents[3] / "ui",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


_UI_DIR = _find_ui_dir()
if _UI_DIR is not None:
    logger.info("Serving the frontend from %s", _UI_DIR)
    app.mount("/", StaticFiles(directory=_UI_DIR, html=True), name="ui")
else:  # pragma: no cover - only when the API runs without the frontend
    logger.warning("No ui/index.html found; serving the API only.")
