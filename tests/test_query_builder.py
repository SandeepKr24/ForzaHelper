"""Query construction: parameterisation, whitelisting, null handling.

These run without a database -- they inspect the generated SQL and params.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forzahelper.models import CarFilters, SearchRequest, Sort
from forzahelper.search import build_order_by, build_search_sql, build_where


def test_no_filters_produces_no_where_clause():
    clauses, params = build_where(CarFilters())
    assert clauses == []
    assert params == {}


def test_range_filters_are_parameterised():
    clauses, params = build_where(CarFilters(year_min=2000, price_cr_max=90000))
    assert "year >= %(year_min)s" in clauses
    assert "price_cr <= %(price_cr_max)s" in clauses
    assert params == {"year_min": 2000, "price_cr_max": 90000}


def test_categorical_filter_is_case_insensitive_and_bound():
    clauses, params = build_where(CarFilters(drivetrain=["awd", " RWD "]))
    assert "lower(drivetrain) = ANY(%(drivetrain)s)" in clauses
    assert params["drivetrain"] == ["awd", "rwd"]


def test_values_never_appear_inline_in_sql():
    request = SearchRequest(
        filters=CarFilters(
            year_min=2001,
            price_cr_max=91234,
            drivetrain=["AWD"],
            make=["Audi"],
            query="RS 6",
        )
    )
    sql, count_sql, params = build_search_sql(request)
    for literal in ("2001", "91234", "AWD", "Audi", "RS 6"):
        assert literal not in sql
        assert literal not in count_sql
    assert params["year_min"] == 2001
    assert params["make"] == ["audi"]


def test_null_rows_are_excluded_by_default():
    """An unknown value must not be shown as satisfying a constraint."""
    clauses, _ = build_where(CarFilters(horsepower_min=400))
    assert clauses == ["horsepower >= %(horsepower_min)s"]
    assert "IS NULL" not in clauses[0]


def test_include_unknown_keeps_null_rows():
    clauses, _ = build_where(CarFilters(horsepower_min=400, include_unknown=True))
    assert clauses == ["(horsepower IS NULL OR horsepower >= %(horsepower_min)s)"]


def test_relevance_sort_ranks_by_horsepower_distance_then_budget():
    order = build_order_by(
        Sort(field="relevance"),
        CarFilters(horsepower_target=450, price_cr_max=90000),
    )
    assert order.startswith("abs(horsepower - %(horsepower_target)s) ASC")
    assert "(%(price_cr_max)s - price_cr) ASC" in order
    assert order.endswith("id ASC")  # deterministic tiebreak for stable paging


def test_explicit_sort_puts_nulls_last_in_both_directions():
    for direction in ("asc", "desc"):
        order = build_order_by(
            Sort(field="price_cr", direction=direction), CarFilters()
        )
        assert "NULLS LAST" in order


def test_sort_field_is_whitelisted():
    with pytest.raises(ValidationError):
        Sort(field="price_cr; DROP TABLE cars")


def test_unknown_filter_field_is_rejected():
    with pytest.raises(ValidationError):
        CarFilters(pi_clas=["A"])  # typo must not be silently ignored


def test_inverted_range_is_rejected():
    with pytest.raises(ValidationError, match="cannot be greater than"):
        CarFilters(price_cr_min=90000, price_cr_max=1000)


def test_limit_is_capped_by_settings():
    request = SearchRequest(filters=CarFilters(), limit=200)
    _, _, params = build_search_sql(request)
    assert params["limit"] <= 200


def test_active_reports_only_set_filters():
    filters = CarFilters(year_min=2000, drivetrain=["AWD"])
    assert filters.active() == {"year_min": 2000, "drivetrain": ["AWD"]}
