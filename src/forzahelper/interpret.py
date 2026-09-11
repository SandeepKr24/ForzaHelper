"""Interpretation and relaxation policy.

Two jobs, both of which must be visible to the user rather than implicit:

  * turning a fuzzy target ("around 450 HP") into an explicit range, and saying
    what range was used (doc section 12);
  * when an exact search returns nothing, proposing labelled alternatives
    instead of quietly loosening what was asked (doc section 16).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, get_settings
from .models import CarFilters, RelaxedResultSet, SearchRequest, Sort


def apply_tolerance(
    filters: CarFilters, settings: Settings | None = None
) -> tuple[CarFilters, list[str]]:
    """Expand a horsepower target into an explicit min/max range.

    An explicit min or max the user gave always wins -- a target never
    overrides a stated bound. Returns the updated filters and the
    human-readable interpretations to show alongside the results.
    """
    settings = settings or get_settings()
    interpretations: list[str] = []

    target = filters.horsepower_target
    if target is None:
        return filters, interpretations

    if filters.horsepower_min is not None or filters.horsepower_max is not None:
        interpretations.append(
            f"Using the horsepower range you gave; {target} HP was treated as a "
            f"ranking preference rather than a filter."
        )
        return filters, interpretations

    tolerance = max(target * settings.default_tolerance_pct, settings.min_tolerance_abs)
    low = max(0, int(round(target - tolerance)))
    high = int(round(target + tolerance))

    updated = filters.model_copy(
        update={"horsepower_min": low, "horsepower_max": high}
    )
    pct = int(round(settings.default_tolerance_pct * 100))
    interpretations.append(
        f"Around {target} HP was interpreted as {low}-{high} HP (+/-{pct}%)."
    )
    return updated, interpretations


@dataclass(frozen=True)
class _Relaxation:
    """One candidate loosening of a filter set."""

    field: str
    description: str
    filters: CarFilters


def _candidates(filters: CarFilters) -> list[_Relaxation]:
    """Propose single-constraint relaxations, most likely to help first.

    Only one constraint is changed per candidate, so the user can see exactly
    which one was blocking the search.
    """
    from .search import boundary_value

    out: list[_Relaxation] = []

    if filters.price_cr_max is not None:
        # Ask the database what the budget would actually have to be, holding
        # every other constraint. An arbitrary percentage bump is usually either
        # too small to help or larger than the user needs.
        without_budget = filters.model_copy(update={"price_cr_max": None})
        cheapest = boundary_value("price_cr", "min", without_budget)
        if cheapest is not None and cheapest > filters.price_cr_max:
            out.append(
                _Relaxation(
                    "price_cr_max",
                    f"Raise the budget from {filters.price_cr_max:,} to "
                    f"{int(cheapest):,} CR",
                    filters.model_copy(update={"price_cr_max": int(cheapest)}),
                )
            )

    if filters.horsepower_min is not None or filters.horsepower_max is not None:
        low = filters.horsepower_min
        high = filters.horsepower_max
        widened_low = max(0, int(low * 0.8)) if low is not None else None
        widened_high = int(high * 1.2) if high is not None else None
        span = "-".join(
            str(v) for v in (widened_low, widened_high) if v is not None
        )
        out.append(
            _Relaxation(
                "horsepower",
                f"Widen the horsepower range to {span} HP",
                filters.model_copy(
                    update={
                        "horsepower_min": widened_low,
                        "horsepower_max": widened_high,
                    }
                ),
            )
        )

    if filters.drivetrain:
        out.append(
            _Relaxation(
                "drivetrain",
                f"Allow any drivetrain, not just {', '.join(filters.drivetrain)}",
                filters.model_copy(update={"drivetrain": None}),
            )
        )

    if filters.year_min is not None:
        earlier = filters.year_min - 5
        out.append(
            _Relaxation(
                "year_min",
                f"Include cars from {earlier} instead of {filters.year_min}",
                filters.model_copy(update={"year_min": earlier}),
            )
        )

    if filters.pi_class:
        out.append(
            _Relaxation(
                "pi_class",
                f"Allow any PI class, not just {', '.join(filters.pi_class)}",
                filters.model_copy(update={"pi_class": None}),
            )
        )

    if filters.country:
        out.append(
            _Relaxation(
                "country",
                f"Allow any country, not just {', '.join(filters.country)}",
                filters.model_copy(update={"country": None}),
            )
        )

    return out


def find_relaxations(
    filters: CarFilters,
    sort: Sort,
    limit: int = 5,
    max_suggestions: int = 3,
) -> list[RelaxedResultSet]:
    """Run each candidate relaxation and keep the ones that find cars.

    Imported lazily to keep this module free of a database dependency at import
    time, which keeps the policy unit-testable on its own.
    """
    from .search import search_cars

    found: list[RelaxedResultSet] = []
    for candidate in _candidates(filters):
        response = search_cars(
            SearchRequest(filters=candidate.filters, sort=sort, limit=limit)
        )
        if response.total > 0:
            found.append(
                RelaxedResultSet(
                    description=(
                        f"{candidate.description}: "
                        f"{response.total} car(s) become eligible."
                    ),
                    relaxed_filter=candidate.field,
                    filters=candidate.filters,
                    count=response.total,
                    results=response.results,
                )
            )
        if len(found) >= max_suggestions:
            break
    return found
