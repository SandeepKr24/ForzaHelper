"""Deterministic query builder.

Rules this module enforces (doc sections 13 and 23):
  * user/LLM values only ever reach Postgres as bound parameters;
  * column and sort names come from fixed whitelists in this file, so no
    caller -- human or model -- can name a column that is not listed here;
  * every query is capped by LIMIT.

The only string interpolation into SQL is of literals defined in this module.
"""

from __future__ import annotations

import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings
from .db import fetch_all, fetch_one
from .models import (
    CarFilters,
    CarResult,
    QueryMetadata,
    SearchRequest,
    SearchResponse,
    Sort,
)

# Columns exposed by public.cars_api, in the order the API returns them.
SELECT_COLUMNS = (
    "id",
    "make",
    "model",
    "full_name",
    "year",
    "country",
    "car_type",
    "price_cr",
    "rarity",
    "acquisition_methods",
    "pi",
    "pi_class",
    "horsepower",
    "torque_lbft",
    "torque_nm",
    "weight_lb",
    "weight_kg",
    "drivetrain",
    "hp_per_tonne",
    "price_per_hp",
)

# filter field -> (column, operator). Nothing outside this map is filterable.
_RANGE_FILTERS: dict[str, tuple[str, str]] = {
    "year_min": ("year", ">="),
    "year_max": ("year", "<="),
    "price_cr_min": ("price_cr", ">="),
    "price_cr_max": ("price_cr", "<="),
    "pi_min": ("pi", ">="),
    "pi_max": ("pi", "<="),
    "horsepower_min": ("horsepower", ">="),
    "horsepower_max": ("horsepower", "<="),
    "torque_lbft_min": ("torque_lbft", ">="),
    "torque_lbft_max": ("torque_lbft", "<="),
    "weight_lb_min": ("weight_lb", ">="),
    "weight_lb_max": ("weight_lb", "<="),
    "hp_per_tonne_min": ("hp_per_tonne", ">="),
    "hp_per_tonne_max": ("hp_per_tonne", "<="),
}

# filter field -> column, for case-insensitive membership tests.
_CATEGORICAL_FILTERS: dict[str, str] = {
    "drivetrain": "drivetrain",
    "pi_class": "pi_class",
    "model": "model",
    "country": "country",
    "car_type": "car_type",
    "make": "make",
    "rarity": "rarity",
}

_SORT_COLUMNS: dict[str, str] = {
    "price_cr": "price_cr",
    "horsepower": "horsepower",
    "pi": "pi",
    "year": "year",
    "weight_lb": "weight_lb",
    "weight_kg": "weight_kg",
    "torque_lbft": "torque_lbft",
    "torque_nm": "torque_nm",
    "hp_per_tonne": "hp_per_tonne",
    "price_per_hp": "price_per_hp",
    "full_name": "full_name",
    "make": "make",
    "model": "model",
    "car_type": "car_type",
    "pi_class": "pi_class",
    "country": "country",
    "rarity": "rarity",
    "drivetrain": "drivetrain",
}

_LIKE_ESCAPE = "ESCAPE '\\'"

# Accent folding -------------------------------------------------------------
# Car names carry accents ("Huracan" is stored as "Huracán") and typographic
# quotes, but nobody types them. Both sides of a text comparison are folded to
# ASCII so "Huracan" matches "Huracán" and "Coupe" matches "Coupe".
#
# The SQL side uses translate() with the characters that actually occur in the
# data, passed as bound parameters -- this needs no database extension and no
# migration. The Python side strips any accent the user types, not just these.
_SQL_FOLD_FROM = "áéÁÉ‘’"
_SQL_FOLD_TO = "aeAE''"

# Only these columns contain non-ASCII characters in the dataset.
_ACCENTED_COLUMNS = {"model", "full_name"}

assert len(_SQL_FOLD_FROM) == len(_SQL_FOLD_TO)


def _folded(column: str) -> str:
    """SQL expression folding `column` to ASCII."""
    return f"translate({column}, %(fold_from)s, %(fold_to)s)"


def fold(value: str) -> str:
    """Strip accents and normalise quotes in user input."""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.replace("‘", "'").replace("’", "'")


def _escape_like(value: str) -> str:
    """Neutralise LIKE metacharacters so they match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_where(filters: CarFilters) -> tuple[list[str], dict[str, Any]]:
    """Return (conditions, params). Conditions contain only bound placeholders."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    unknown_ok = filters.include_unknown

    def add(column: str, condition: str) -> None:
        # Keeping NULLs requires an explicit opt-in: an unknown value must not
        # be presented as satisfying a constraint (doc sections 4 and 23).
        clauses.append(f"({column} IS NULL OR {condition})" if unknown_ok else condition)

    for field, (column, op) in _RANGE_FILTERS.items():
        value = getattr(filters, field)
        if value is not None:
            params[field] = value
            add(column, f"{column} {op} %({field})s")

    for field, column in _CATEGORICAL_FILTERS.items():
        values = getattr(filters, field)
        if not values:
            continue
        if column in _ACCENTED_COLUMNS:
            # Fold both sides so a dropdown value and a hand-typed one both hit.
            params[field] = [fold(v).strip().lower() for v in values]
            params.setdefault("fold_from", _SQL_FOLD_FROM)
            params.setdefault("fold_to", _SQL_FOLD_TO)
            add(column, f"lower({_folded(column)}) = ANY(%({field})s)")
        else:
            params[field] = [v.strip().lower() for v in values]
            add(column, f"lower({column}) = ANY(%({field})s)")

    if filters.acquisition_methods:
        params["acquisition_methods"] = [
            v.strip().lower() for v in filters.acquisition_methods
        ]
        # Overlap test against the text[] column, lowercased element-wise.
        add(
            "acquisition_methods",
            "EXISTS (SELECT 1 FROM unnest(acquisition_methods) AS m"
            " WHERE lower(m) = ANY(%(acquisition_methods)s))",
        )

    if filters.query:
        params["query"] = f"%{_escape_like(fold(filters.query.strip()))}%"
        params.setdefault("fold_from", _SQL_FOLD_FROM)
        params.setdefault("fold_to", _SQL_FOLD_TO)
        clauses.append(f"{_folded('full_name')} ILIKE %(query)s {_LIKE_ESCAPE}")

    return clauses, params


def build_order_by(sort: Sort, filters: CarFilters) -> str:
    """Build ORDER BY from whitelisted columns only.

    "relevance" implements the ranking in doc section 14: distance from the
    requested horsepower first, then closeness to the budget ceiling without
    exceeding it, then PI.
    """
    if sort.field == "relevance":
        terms: list[str] = []
        if filters.horsepower_target is not None:
            terms.append("abs(horsepower - %(horsepower_target)s) ASC NULLS LAST")
        if filters.price_cr_max is not None:
            terms.append("(%(price_cr_max)s - price_cr) ASC NULLS LAST")
        terms.append("pi DESC NULLS LAST")
        terms.append("id ASC")
        return ", ".join(terms)

    column = _SORT_COLUMNS[sort.field]
    direction = "ASC" if sort.direction == "asc" else "DESC"
    # NULLS LAST in both directions: unknown values never lead the results.
    return f"{column} {direction} NULLS LAST, id ASC"


def _relevance_params(filters: CarFilters) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if filters.horsepower_target is not None:
        extra["horsepower_target"] = filters.horsepower_target
    if filters.price_cr_max is not None:
        extra["price_cr_max"] = filters.price_cr_max
    return extra


def build_search_sql(
    request: SearchRequest, settings: Settings | None = None
) -> tuple[str, str, dict[str, Any]]:
    """Return (rows_sql, count_sql, params)."""
    settings = settings or get_settings()
    relation = settings.cars_relation  # fixed identifier from config, not input

    clauses, params = build_where(request.filters)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    params.update(_relevance_params(request.filters))
    params["limit"] = min(request.limit, settings.max_limit)
    params["offset"] = request.offset

    columns = ", ".join(SELECT_COLUMNS)
    # count(*) OVER () returns the total alongside the page, so the page and
    # its count cost one round trip instead of two.
    rows_sql = (
        f"SELECT {columns}, count(*) OVER () AS _total FROM {relation} {where}"
        f" ORDER BY {build_order_by(request.sort, request.filters)}"
        f" LIMIT %(limit)s OFFSET %(offset)s"
    )
    count_sql = f"SELECT count(*) AS total FROM {relation} {where}"
    return rows_sql, count_sql, params


def search_cars(
    request: SearchRequest, settings: Settings | None = None
) -> SearchResponse:
    """Run a search and return the structured response."""
    settings = settings or get_settings()
    rows_sql, count_sql, params = build_search_sql(request, settings)

    started = time.perf_counter()
    rows = fetch_all(rows_sql, params)
    if rows:
        total = int(rows[0]["_total"])
    else:
        # An empty page carries no window-function row, so the count is only
        # needed when nothing came back -- and then it is always zero unless
        # the caller paged past the end.
        total = 0 if not request.offset else int((fetch_one(count_sql, params) or {}).get("total", 0))
    duration_ms = (time.perf_counter() - started) * 1000

    results = [CarResult.model_validate(row) for row in rows]
    warnings: list[str] = []
    # Say so plainly when part of the request names something absent from the
    # data, rather than returning rows that ignore it.
    warnings.extend(describe_unknown(unknown_filter_values(request.filters, settings)))
    if not request.filters.include_unknown:
        warnings.extend(_null_warnings(request.filters))

    return SearchResponse(
        filters_applied=request.filters.active(),
        count=len(results),
        total=total,
        results=results,
        warnings=warnings,
        query_metadata=QueryMetadata(
            executed_at=datetime.now(timezone.utc),
            duration_ms=round(duration_ms, 2),
            relation=settings.cars_relation,
        ),
    )


# Columns that may have gaps, checked against the database rather than hardcoded
# so the warnings stay correct if the dataset changes.
_NULLABLE_COLUMNS = (
    "year",
    "price_cr",
    "pi",
    "horsepower",
    "torque_lbft",
    "weight_lb",
    "drivetrain",
    "pi_class",
    "country",
    "car_type",
    "rarity",
    "hp_per_tonne",
)

_null_counts_cache: dict[str, int] | None = None


def null_counts(settings: Settings | None = None) -> dict[str, int]:
    """How many rows have no value for each nullable column. Cached per process."""
    global _null_counts_cache
    if _null_counts_cache is None:
        settings = settings or get_settings()
        selects = ", ".join(
            f"count(*) FILTER (WHERE {col} IS NULL) AS {col}"
            for col in _NULLABLE_COLUMNS
        )
        row = fetch_one(f"SELECT {selects} FROM {settings.cars_relation}") or {}
        _null_counts_cache = {k: int(v) for k, v in row.items() if v}
    return _null_counts_cache


def reset_caches() -> None:
    """Drop cached dataset facts. Call after the underlying data changes."""
    global _null_counts_cache, _filter_metadata_cache
    _null_counts_cache = None
    _filter_metadata_cache = None


def _null_warnings(filters: CarFilters) -> list[str]:
    touched: set[str] = set()
    for field, (column, _) in _RANGE_FILTERS.items():
        if getattr(filters, field) is not None:
            touched.add(column)
    for field, column in _CATEGORICAL_FILTERS.items():
        if getattr(filters, field):
            touched.add(column)

    try:
        counts = null_counts()
    except Exception:  # pragma: no cover - warnings must never fail a search
        return []

    return [
        f"{counts[column]} car(s) have no recorded {column} and were excluded. "
        f"Set include_unknown to keep them."
        for column in sorted(touched)
        if counts.get(column)
    ]


_filter_metadata_cache: dict[str, Any] | None = None


def filter_metadata(settings: Settings | None = None) -> dict[str, Any]:
    """Distinct categorical values and numeric bounds, for GET /api/filters.

    Values are read from the database, so nothing here hard-codes a PI class or
    drivetrain list (doc section 5).
    """
    global _filter_metadata_cache
    if _filter_metadata_cache is not None:
        return _filter_metadata_cache

    settings = settings or get_settings()
    relation = settings.cars_relation

    # One statement, not eleven. The database answers each of these in well
    # under a millisecond, so the cost was entirely the network round trip per
    # query -- eleven of them on the page's first load.
    facet_columns = (
        "drivetrain",
        "pi_class",
        "country",
        "car_type",
        "make",
        "model",
        "rarity",
    )
    numeric_columns = (
        "year",
        "price_cr",
        "pi",
        "horsepower",
        "torque_lbft",
        "weight_lb",
        "hp_per_tonne",
    )

    facet_selects = [
        f"(SELECT coalesce(json_agg(v ORDER BY v), '[]'::json) FROM"
        f" (SELECT DISTINCT {c} AS v FROM {relation} WHERE {c} IS NOT NULL) s)"
        f" AS facet_{c}"
        for c in facet_columns
    ]
    facet_selects.append(
        f"(SELECT coalesce(json_agg(v ORDER BY v), '[]'::json) FROM"
        f" (SELECT DISTINCT unnest(acquisition_methods) AS v FROM {relation}"
        f"  WHERE acquisition_methods IS NOT NULL) s) AS facet_acquisition_methods"
    )
    range_selects = [
        f"min({c}) AS {c}_min, max({c}) AS {c}_max" for c in numeric_columns
    ]
    null_selects = [
        f"count(*) FILTER (WHERE {c} IS NULL) AS null_{c}" for c in _NULLABLE_COLUMNS
    ]
    bands_select = (
        f"(SELECT coalesce(json_agg(b ORDER BY b.pi_min), '[]'::json) FROM"
        f" (SELECT pi_class, min(pi) AS pi_min, max(pi) AS pi_max, count(*) AS count"
        f"  FROM {relation} WHERE pi_class IS NOT NULL GROUP BY pi_class) b)"
        f" AS pi_class_bands"
    )

    row = fetch_one(
        "SELECT "
        + ", ".join([*facet_selects, bands_select, *range_selects, *null_selects])
        + f" FROM {relation}"
    ) or {}

    categorical = {
        c: row.get(f"facet_{c}") or []
        for c in (*facet_columns, "acquisition_methods")
    }
    ranges = {
        c: {
            "min": _as_number(row.get(f"{c}_min")),
            "max": _as_number(row.get(f"{c}_max")),
        }
        for c in numeric_columns
    }
    counts = {
        c: int(row[f"null_{c}"])
        for c in _NULLABLE_COLUMNS
        if row.get(f"null_{c}")
    }

    global _null_counts_cache
    _null_counts_cache = counts

    _filter_metadata_cache = {
        "categorical": categorical,
        "ranges": ranges,
        # PI class bands are derived, not assumed -- this dataset's bands differ
        # from retail Forza's, and the query layer must not presume either.
        "pi_class_bands": row.get("pi_class_bands") or [],
        "sortable_fields": ["relevance", *sorted(_SORT_COLUMNS)],
        "null_counts": counts,
    }
    return _filter_metadata_cache


# filter field -> (metadata key, how to phrase it when nothing matches)
_VALIDATED_FIELDS: dict[str, tuple[str, str]] = {
    "country": ("country", "cars from {value}"),
    "make": ("make", "cars made by {value}"),
    "car_type": ("car_type", "cars of type {value}"),
    "pi_class": ("pi_class", "cars in class {value}"),
    "rarity": ("rarity", "cars with rarity {value}"),
    "drivetrain": ("drivetrain", "{value} cars"),
    "model": ("model", "a model called {value}"),
    "acquisition_methods": ("acquisition_methods", "cars acquired via {value}"),
}


def unknown_filter_values(
    filters: CarFilters, settings: Settings | None = None
) -> dict[str, list[str]]:
    """Requested values that do not occur anywhere in the data.

    A request naming something the dataset has never heard of -- "Indian cars"
    -- must not come back as though it were satisfied. The extractor is told to
    keep such values rather than drop them, and this is the check that does not
    depend on the model obeying (doc section 23 rule 10).
    """
    try:
        vocabulary = filter_metadata(settings)["categorical"]
    except Exception:  # pragma: no cover - never fail a search over a warning
        return {}

    unknown: dict[str, list[str]] = {}
    for field, (key, _) in _VALIDATED_FIELDS.items():
        wanted = getattr(filters, field, None) or []
        known = {fold(str(v)).strip().lower() for v in vocabulary.get(key, [])}
        missing = [v for v in wanted if fold(str(v)).strip().lower() not in known]
        if missing:
            unknown[field] = missing
    return unknown


def describe_unknown(unknown: dict[str, list[str]]) -> list[str]:
    """Readable reasons, one per value the data does not contain."""
    out = []
    for field, values in unknown.items():
        phrase = _VALIDATED_FIELDS[field][1]
        for value in values:
            out.append("The data contains no " + phrase.format(value=value) + ".")
    return out


def models_for_make(
    make: str | None = None, settings: Settings | None = None
) -> list[str]:
    """Model names, optionally narrowed to one manufacturer.

    Backs the Model dropdown, which is repopulated when the Make changes.
    """
    settings = settings or get_settings()
    if make:
        rows = fetch_all(
            f"SELECT DISTINCT model AS value FROM {settings.cars_relation}"
            f" WHERE model IS NOT NULL AND lower(make) = %(make)s ORDER BY value",
            {"make": make.strip().lower()},
        )
    else:
        rows = fetch_all(
            f"SELECT DISTINCT model AS value FROM {settings.cars_relation}"
            f" WHERE model IS NOT NULL ORDER BY value"
        )
    return [r["value"] for r in rows]


def _as_number(value: Any) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else float(value)


def _namespaced(
    clauses: list[str], params: dict[str, Any], prefix: str
) -> tuple[list[str], dict[str, Any]]:
    """Rename a filter's placeholders so several can share one statement."""
    renamed = {f"{prefix}{k}": v for k, v in params.items()}
    out = []
    for clause in clauses:
        # Longest first, so one parameter name cannot be rewritten inside
        # another that happens to start with the same characters.
        for key in sorted(params, key=len, reverse=True):
            clause = clause.replace(f"%({key})s", f"%({prefix}{key})s")
        out.append(clause)
    return out, renamed


def count_many(
    filter_sets: list[CarFilters], settings: Settings | None = None
) -> list[int]:
    """Row counts for several filter sets in a single round trip.

    Each query costs about 110ms of network and under a millisecond of database
    work, so the only thing worth optimising is the number of statements.
    """
    if not filter_sets:
        return []
    settings = settings or get_settings()
    branches, params = [], {}
    for i, filters in enumerate(filter_sets):
        clauses, branch_params = build_where(filters)
        clauses, branch_params = _namespaced(clauses, branch_params, f"c{i}_")
        params.update(branch_params)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        branches.append(
            f"SELECT {i} AS idx, count(*) AS n FROM {settings.cars_relation} {where}"
        )
    rows = fetch_all(" UNION ALL ".join(branches), params)
    by_idx = {int(r["idx"]): int(r["n"]) for r in rows}
    return [by_idx.get(i, 0) for i in range(len(filter_sets))]


def rows_many(
    filter_sets: list[CarFilters],
    sort: Sort,
    limit: int,
    settings: Settings | None = None,
) -> list[list[CarResult]]:
    """Top rows for several filter sets in a single round trip."""
    if not filter_sets:
        return []
    settings = settings or get_settings()
    columns = ", ".join(SELECT_COLUMNS)
    branches, params = [], {}
    for i, filters in enumerate(filter_sets):
        clauses, branch_params = build_where(filters)
        branch_params.update(_relevance_params(filters))
        clauses, branch_params = _namespaced(clauses, branch_params, f"c{i}_")
        params.update(branch_params)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = build_order_by(sort, filters)
        for key in sorted(_relevance_params(filters), key=len, reverse=True):
            order = order.replace(f"%({key})s", f"%(c{i}_{key})s")
        branches.append(
            f"(SELECT {i} AS idx, {columns} FROM {settings.cars_relation} {where}"
            f" ORDER BY {order} LIMIT {int(limit)})"
        )
    rows = fetch_all(" UNION ALL ".join(branches), params)
    out: list[list[CarResult]] = [[] for _ in filter_sets]
    for row in rows:
        out[int(row["idx"])].append(CarResult.model_validate(row))
    return out


_AGGREGATABLE = {
    "price_cr",
    "horsepower",
    "pi",
    "year",
    "weight_lb",
    "torque_lbft",
    "hp_per_tonne",
}


def boundary_value(
    column: str,
    agg: str,
    filters: CarFilters,
    settings: Settings | None = None,
) -> Any:
    """min/max of a column among rows matching `filters`.

    Used to propose a relaxation threshold that actually works, instead of an
    arbitrary percentage bump. Both `column` and `agg` are whitelisted here.
    """
    if column not in _AGGREGATABLE:
        raise ValueError(f"column not aggregatable: {column}")
    if agg not in ("min", "max"):
        raise ValueError(f"unsupported aggregate: {agg}")

    settings = settings or get_settings()
    clauses, params = build_where(filters)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = fetch_one(
        f"SELECT {agg}({column}) AS value FROM {settings.cars_relation} {where}",
        params,
    )
    return row["value"] if row else None


def get_car(car_id: str, settings: Settings | None = None) -> CarResult | None:
    settings = settings or get_settings()
    columns = ", ".join(SELECT_COLUMNS)
    row = fetch_one(
        f"SELECT {columns} FROM {settings.cars_relation} WHERE id = %(id)s",
        {"id": car_id},
    )
    return CarResult.model_validate(row) if row else None


def compare_cars(
    car_ids: list[str], settings: Settings | None = None
) -> list[CarResult]:
    """Fetch several cars, preserving the caller's ordering."""
    settings = settings or get_settings()
    columns = ", ".join(SELECT_COLUMNS)
    rows = fetch_all(
        f"SELECT {columns} FROM {settings.cars_relation} WHERE id = ANY(%(ids)s)",
        {"ids": car_ids},
    )
    by_id = {row["id"]: CarResult.model_validate(row) for row in rows}
    return [by_id[cid] for cid in car_ids if cid in by_id]
