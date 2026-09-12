"""Chat orchestration.

A thin layer over the deterministic search (doc section 25). The order is fixed:

    message -> extract -> validate -> apply tolerance -> SQL -> rank
            -> relax if empty -> structured response

The prose in `message` is a summary of what the structured fields already say.
The frontend renders `filters`, `results` and `interpretations`; it must never
need to parse the prose to know what matched (doc section 6).
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..interpret import apply_tolerance, find_relaxations
from ..models import (
    CarFilters,
    ChatRequest,
    ChatResponse,
    ConversationState,
    SearchRequest,
)
from ..search import describe_unknown, search_cars, unknown_filter_values
from .extraction import ConstraintExtractor, get_extractor

# Words that imply a threshold the user has not actually given. Rather than
# invent a number, the assistant says what it needs (doc section 15).
_VAGUE_TERMS = {
    "cheap": "a maximum price in CR",
    "affordable": "a maximum price in CR",
    "budget": "a maximum price in CR",
    "expensive": "a minimum price in CR",
    "fast": "a target horsepower, top PI, or a PI class",
    "quick": "a target horsepower or a PI class",
    "powerful": "a target or minimum horsepower",
    "light": "a maximum weight in lb",
    "good": "which quality matters -- power, price, or PI",
    "best": "which quality matters -- power, price, or PI",
}


def _clarification_for(message: str, filters: CarFilters) -> str | None:
    """Ask about vague wording, but only when it left the search unconstrained."""
    if filters.active():
        return None
    text = message.lower()
    hits = [need for term, need in _VAGUE_TERMS.items() if term in text]
    if not hits:
        return None
    unique = list(dict.fromkeys(hits))
    return (
        "I did not apply a filter for that, because it depends on what you mean. "
        f"Could you give me {unique[0]}?"
    )


def _summarise(
    filters: CarFilters,
    total: int,
    shown: int,
    relaxed_count: int,
    unknown_reasons: list[str] | None = None,
) -> str:
    if total == 0:
        if unknown_reasons:
            # The request named something the dataset does not have, so this is
            # not a near miss -- nothing could ever match it.
            reason = " ".join(unknown_reasons)
            if relaxed_count:
                return (
                    f"No eligible cars found. {reason} Here are the closest "
                    f"alternatives, each with the constraint that had to change."
                )
            return f"No eligible cars found. {reason}"
        if relaxed_count:
            return (
                "No exact matches. Here are the closest alternatives, each with "
                "the constraint that had to change."
            )
        return (
            "No cars match those constraints, and loosening any single one of "
            "them did not help either."
        )

    if not filters.active():
        body = f"Showing {shown} of {total} cars."
    else:
        body = f"I found {total} car{'s' if total != 1 else ''} matching your "
        body += "requirements."
        if shown < total:
            body += f" Showing the top {shown}."
    return body


def chat(
    request: ChatRequest,
    extractor: ConstraintExtractor | None = None,
    settings: Settings | None = None,
) -> ChatResponse:
    """Run one conversational turn."""
    settings = settings or get_settings()
    extractor = extractor or get_extractor(settings)

    state = request.conversation

    # 1. Extract, carrying forward the constraints already in play.
    raw_filters = extractor.extract(request.message, state.active_filters)

    # 2. Re-validate: the extractor's output is untrusted input either way.
    filters = CarFilters.model_validate(raw_filters.model_dump())

    # 3. Turn fuzzy targets into explicit ranges, and say so.
    filters, interpretations = apply_tolerance(filters, settings)

    # 4. Deterministic search.
    search_request = SearchRequest(
        filters=filters, sort=state.sort, limit=request.limit
    )
    response = search_cars(search_request, settings)

    # 5. Nothing found -> offer labelled alternatives, never silent relaxation.
    relaxed = []
    if response.total == 0:
        relaxed = find_relaxations(filters, state.sort)

    clarification = _clarification_for(request.message, filters)
    unknown_reasons = describe_unknown(unknown_filter_values(filters, settings))

    return ChatResponse(
        message=_summarise(
            filters, response.total, response.count, len(relaxed), unknown_reasons
        ),
        filters=filters.active(),
        interpretations=interpretations + unknown_reasons,
        count=response.count,
        total=response.total,
        results=response.results,
        relaxed_results=relaxed,
        clarification=clarification,
        warnings=response.warnings,
        conversation=ConversationState(
            active_filters=filters,
            sort=state.sort,
            previous_result_ids=[car.id for car in response.results],
        ),
        query_metadata=response.query_metadata,
    )
