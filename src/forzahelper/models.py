"""Request/response contracts.

CarFilters is the single structured representation of "what the user asked for".
The LLM produces it, Pydantic validates it, and the query builder is the only
thing that turns it into SQL. Nothing downstream of validation ever sees free
text from the user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SortField = Literal[
    "relevance",
    "price_cr",
    "horsepower",
    "pi",
    "year",
    "weight_lb",
    "torque_lbft",
    "hp_per_tonne",
    "price_per_hp",
    "full_name",
]
SortDirection = Literal["asc", "desc"]


class Sort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: SortField = "relevance"
    direction: SortDirection = "asc"


class CarFilters(BaseModel):
    """Structured constraints. Every field is optional; None means unconstrained.

    Categorical lists are matched case-insensitively against the values actually
    present in the database -- no enum is hard-coded here, per doc section 5.
    """

    model_config = ConfigDict(extra="forbid")

    year_min: int | None = Field(default=None, ge=1900, le=3000)
    year_max: int | None = Field(default=None, ge=1900, le=3000)

    price_cr_min: int | None = Field(default=None, ge=0)
    price_cr_max: int | None = Field(default=None, ge=0)

    pi_min: int | None = Field(default=None, ge=0, le=999)
    pi_max: int | None = Field(default=None, ge=0, le=999)

    horsepower_min: int | None = Field(default=None, ge=0)
    horsepower_max: int | None = Field(default=None, ge=0)
    horsepower_target: int | None = Field(default=None, ge=0)

    torque_lbft_min: int | None = Field(default=None, ge=0)
    torque_lbft_max: int | None = Field(default=None, ge=0)

    weight_lb_min: int | None = Field(default=None, ge=0)
    weight_lb_max: int | None = Field(default=None, ge=0)

    hp_per_tonne_min: float | None = Field(default=None, ge=0)
    hp_per_tonne_max: float | None = Field(default=None, ge=0)

    drivetrain: list[str] | None = None
    pi_class: list[str] | None = None
    country: list[str] | None = None
    car_type: list[str] | None = None
    make: list[str] | None = None
    rarity: list[str] | None = None
    acquisition_methods: list[str] | None = None

    # Free-text match on make/model. Passed as a bound parameter, never inlined.
    query: str | None = Field(default=None, max_length=120)

    # If True, rows with a NULL in a filtered column are kept rather than
    # dropped. Default False: a NULL cannot be shown to satisfy a constraint.
    include_unknown: bool = False

    _RANGES = (
        ("year", "year_min", "year_max"),
        ("price_cr", "price_cr_min", "price_cr_max"),
        ("pi", "pi_min", "pi_max"),
        ("horsepower", "horsepower_min", "horsepower_max"),
        ("torque_lbft", "torque_lbft_min", "torque_lbft_max"),
        ("weight_lb", "weight_lb_min", "weight_lb_max"),
        ("hp_per_tonne", "hp_per_tonne_min", "hp_per_tonne_max"),
    )

    @model_validator(mode="after")
    def _check_ranges(self) -> "CarFilters":
        for label, lo_name, hi_name in self._RANGES:
            lo, hi = getattr(self, lo_name), getattr(self, hi_name)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{lo_name} cannot be greater than {hi_name}")
        return self

    def active(self) -> dict[str, Any]:
        """Only the constraints that are actually set -- for filter chips."""
        return {
            k: v
            for k, v in self.model_dump().items()
            if v is not None and not (k == "include_unknown" and v is False)
        }


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: CarFilters = Field(default_factory=CarFilters)
    sort: Sort = Field(default_factory=Sort)
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=10_000)] = 0


class CarResult(BaseModel):
    """One car row. Mirrors the CarResult shape in doc section 9."""

    model_config = ConfigDict(extra="ignore")

    id: str
    make: str
    model: str
    full_name: str
    year: int | None = None
    country: str | None = None
    car_type: str | None = None
    price_cr: int | None = None
    rarity: str | None = None
    acquisition_methods: list[str] | None = None
    pi: int | None = None
    pi_class: str | None = None
    horsepower: int | None = None
    torque_lbft: int | None = None
    weight_lb: int | None = None
    drivetrain: str | None = None
    hp_per_tonne: float | None = None
    price_per_hp: float | None = None


class RelaxedResultSet(BaseModel):
    """Alternatives offered when the exact search found nothing.

    Always labelled, never substituted silently (doc section 16).
    """

    model_config = ConfigDict(extra="forbid")

    description: str
    relaxed_filter: str
    filters: CarFilters
    count: int
    results: list[CarResult]


class QueryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executed_at: datetime
    duration_ms: float
    relation: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters_applied: dict[str, Any]
    interpretations: list[str] = Field(default_factory=list)
    count: int
    total: int
    results: list[CarResult]
    relaxed_results: list[RelaxedResultSet] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    query_metadata: QueryMetadata | None = None


class ConversationState(BaseModel):
    """Structured state carried between turns (doc section 17).

    Only the normalised constraints and the ids last shown are kept -- no
    transcript, per doc section 17's instruction not to store unnecessary
    conversational data.
    """

    model_config = ConfigDict(extra="forbid")

    active_filters: CarFilters = Field(default_factory=CarFilters)
    sort: Sort = Field(default_factory=Sort)
    previous_result_ids: list[str] = Field(default_factory=list, max_length=200)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=2000)]
    conversation: ConversationState = Field(default_factory=ConversationState)
    limit: Annotated[int, Field(ge=1, le=200)] = 50


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    filters: dict[str, Any]
    interpretations: list[str] = Field(default_factory=list)
    count: int
    total: int
    results: list[CarResult]
    relaxed_results: list[RelaxedResultSet] = Field(default_factory=list)
    clarification: str | None = None
    warnings: list[str] = Field(default_factory=list)
    conversation: ConversationState
    query_metadata: QueryMetadata | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
