"""SQL injection attempts, per doc section 24.

The guarantee is not "the string is escaped" but "the string is never SQL": it
arrives as a bound parameter, so it can only ever be compared as a value.
"""

from __future__ import annotations

import pytest

from forzahelper.models import CarFilters, SearchRequest
from forzahelper.search import (
    _SQL_FOLD_FROM,
    _SQL_FOLD_TO,
    build_search_sql,
    build_where,
    search_cars,
)

from .conftest import requires_db

PAYLOADS = [
    "'; DROP TABLE cars; --",
    "' OR '1'='1",
    "1; DELETE FROM cars WHERE 1=1",
    "x' UNION SELECT null,null,null--",
    "%' OR full_name LIKE '%",
    "\\'; TRUNCATE cars; --",
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_free_text_payload_stays_a_parameter(payload):
    clauses, params = build_where(CarFilters(query=payload))

    # The statement is a fixed string regardless of what the payload contains.
    # full_name is accent-folded, and even the fold table is bound rather than
    # inlined, so no part of this clause varies with user input.
    assert clauses == [
        "translate(full_name, %(fold_from)s, %(fold_to)s) ILIKE %(query)s ESCAPE '\\'"
    ]

    # The payload exists only as a bound value. The other two parameters are
    # fixed constants from search.py, never anything the caller supplied.
    assert set(params) == {"query", "fold_from", "fold_to"}
    assert params["fold_from"] == _SQL_FOLD_FROM
    assert params["fold_to"] == _SQL_FOLD_TO
    sql, count_sql, _ = build_search_sql(SearchRequest(filters=CarFilters(query=payload)))
    for fragment in ("DROP", "DELETE", "UNION", "TRUNCATE", "--"):
        assert fragment not in sql.upper()
        assert fragment not in count_sql.upper()


@pytest.mark.parametrize("payload", PAYLOADS)
def test_categorical_payload_stays_a_parameter(payload):
    request = SearchRequest(filters=CarFilters(make=[payload]))
    sql, count_sql, params = build_search_sql(request)
    assert payload not in sql
    assert payload not in count_sql
    assert params["make"] == [payload.strip().lower()]


def test_like_metacharacters_are_escaped_not_treated_as_wildcards():
    _, params = build_where(CarFilters(query="100%_off"))
    assert params["query"] == "%100\\%\\_off%"


@requires_db
@pytest.mark.parametrize("payload", PAYLOADS)
def test_payloads_execute_harmlessly_and_match_nothing(payload):
    response = search_cars(SearchRequest(filters=CarFilters(query=payload)))
    assert response.total == 0


@requires_db
def test_table_still_intact_after_injection_attempts():
    """The obvious follow-up: nothing was dropped or emptied."""
    response = search_cars(SearchRequest(filters=CarFilters(), limit=1))
    assert response.total == 635
