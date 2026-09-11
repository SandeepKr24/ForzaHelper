"""End-to-end tests against the live database and the HTTP layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from forzahelper.api import app
from forzahelper.chat.extraction import RuleBasedExtractor
from forzahelper.models import CarFilters, ChatRequest, SearchRequest, Sort
from forzahelper.search import search_cars

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture(scope="module")
def client():
    """Client pinned to the deterministic extractor.

    A default `pytest` run must not depend on a configured model, and must not
    spend money on API calls.
    """
    from forzahelper.api import _extractor_dependency

    app.dependency_overrides[_extractor_dependency] = RuleBasedExtractor
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------- search layer


def test_exact_numeric_filter():
    response = search_cars(SearchRequest(filters=CarFilters(horsepower_min=1000)))
    assert response.total > 0
    assert all(car.horsepower >= 1000 for car in response.results)


def test_range_filter():
    response = search_cars(
        SearchRequest(filters=CarFilters(year_min=2020, year_max=2022), limit=200)
    )
    assert all(2020 <= car.year <= 2022 for car in response.results)


def test_categorical_filter_matches_case_insensitively():
    lower = search_cars(SearchRequest(filters=CarFilters(drivetrain=["awd"])))
    upper = search_cars(SearchRequest(filters=CarFilters(drivetrain=["AWD"])))
    assert lower.total == upper.total > 0


def test_multiple_filters_combine_as_and():
    response = search_cars(
        SearchRequest(
            filters=CarFilters(
                drivetrain=["AWD"], country=["Japan"], year_min=2015
            ),
            limit=200,
        )
    )
    for car in response.results:
        assert car.drivetrain == "AWD"
        assert car.country == "Japan"
        assert car.year >= 2015


def test_null_rows_excluded_by_default_but_kept_on_request():
    strict = search_cars(SearchRequest(filters=CarFilters(horsepower_min=0)))
    lenient = search_cars(
        SearchRequest(filters=CarFilters(horsepower_min=0, include_unknown=True))
    )
    assert lenient.total > strict.total


def test_excluded_nulls_are_reported_as_a_warning():
    response = search_cars(SearchRequest(filters=CarFilters(drivetrain=["AWD"])))
    assert any("no recorded drivetrain" in w for w in response.warnings)


def test_relevance_ranking_orders_by_horsepower_distance():
    response = search_cars(
        SearchRequest(
            filters=CarFilters(
                horsepower_target=450, horsepower_min=400, horsepower_max=500
            ),
            sort=Sort(field="relevance"),
            limit=10,
        )
    )
    distances = [abs(car.horsepower - 450) for car in response.results]
    assert distances == sorted(distances)


def test_pagination_is_stable_and_non_overlapping():
    base = dict(filters=CarFilters(drivetrain=["RWD"]), sort=Sort(field="price_cr"))
    first = search_cars(SearchRequest(**base, limit=10, offset=0))
    second = search_cars(SearchRequest(**base, limit=10, offset=10))
    assert {c.id for c in first.results}.isdisjoint({c.id for c in second.results})
    assert first.total == second.total


def test_derived_power_to_weight_is_consistent():
    response = search_cars(
        SearchRequest(filters=CarFilters(horsepower_min=500), limit=5)
    )
    for car in response.results:
        expected = car.horsepower / (car.weight_lb / 2204.62)
        assert car.hp_per_tonne == pytest.approx(expected, rel=0.001)


# ----------------------------------------------------------- no-result recovery


def test_no_results_returns_zero_not_a_silent_relaxation():
    response = search_cars(
        SearchRequest(
            filters=CarFilters(
                drivetrain=["FWD"], horsepower_min=2000, price_cr_max=5000
            )
        )
    )
    assert response.total == 0
    assert response.results == []


def test_relaxation_suggests_a_threshold_that_actually_works():
    from forzahelper.interpret import find_relaxations

    filters = CarFilters(
        year_min=2015,
        price_cr_max=20000,
        drivetrain=["AWD"],
        horsepower_min=405,
        horsepower_max=495,
    )
    assert search_cars(SearchRequest(filters=filters)).total == 0

    relaxations = find_relaxations(filters, Sort())
    assert relaxations
    for relaxed in relaxations:
        assert relaxed.count > 0
        # Each suggestion is labelled with the single constraint that changed.
        assert relaxed.relaxed_filter
        assert search_cars(SearchRequest(filters=relaxed.filters)).total == relaxed.count


# --------------------------------------------------------------------- chat


def test_chat_end_to_end_matches_the_doc_example():
    from forzahelper.chat.orchestrator import chat

    response = chat(
        ChatRequest(
            message="I want a car built 2000 or later, under 90k CR, AWD stock, "
            "and around 450 HP.",
            limit=10,
        ),
        extractor=RuleBasedExtractor(),
    )
    assert response.total > 0
    assert response.filters["year_min"] == 2000
    assert response.filters["horsepower_min"] == 405
    assert response.filters["horsepower_max"] == 495
    assert any("405-495" in note for note in response.interpretations)
    for car in response.results:
        assert car.drivetrain == "AWD"
        assert car.year >= 2000
        assert car.price_cr <= 90000


def test_chat_preserves_constraints_across_turns():
    from forzahelper.chat.orchestrator import chat

    extractor = RuleBasedExtractor()
    first = chat(
        ChatRequest(message="AWD cars under 100k with around 500 hp"), extractor
    )
    second = chat(
        ChatRequest(message="only Japanese cars", conversation=first.conversation),
        extractor,
    )
    assert second.filters["drivetrain"] == ["AWD"]
    assert second.filters["price_cr_max"] == 100000
    assert second.filters["country"] == ["Japan"]


def test_chat_asks_rather_than_guessing_a_threshold():
    from forzahelper.chat.orchestrator import chat

    response = chat(
        ChatRequest(message="I want something cheap"), RuleBasedExtractor()
    )
    assert response.clarification is not None
    assert "price_cr_max" not in response.filters


# ---------------------------------------------------------------------- HTTP


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_metadata_car_count_comes_from_the_database(client):
    assert client.get("/api/metadata").json()["car_count"] == 635


def test_filters_metadata_is_read_from_data_not_hardcoded(client):
    body = client.get("/api/filters").json()
    assert body["categorical"]["drivetrain"] == ["AWD", "FWD", "RWD"]
    # This dataset's PI bands differ from retail Forza's; they must be derived.
    bands = {b["pi_class"]: (b["pi_min"], b["pi_max"]) for b in body["pi_class_bands"]}
    assert bands["A"] == (601, 700)
    assert "R" in bands


def test_list_cars_pagination(client):
    body = client.get("/api/cars", params={"limit": 5}).json()
    assert len(body["results"]) == 5
    assert body["pagination"] == {"page": 1, "limit": 5, "total": 635}


def test_car_detail_and_404(client):
    listed = client.get("/api/cars", params={"limit": 1}).json()["results"][0]
    assert client.get(f"/api/cars/{listed['id']}").json()["id"] == listed["id"]

    missing = client.get("/api/cars/no-such-car-1999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_accented_names_survive_the_round_trip(client):
    """The 28 repaired rows must come back with their accents intact."""
    body = client.get("/api/cars", params={"q": "Huracan", "limit": 50}).json()
    hits = client.get("/api/cars", params={"q": "Hurac", "limit": 50}).json()["results"]
    assert hits, "expected Lamborghini Huracan entries"
    assert any("á" in car["full_name"] for car in hits)
    assert not any("�" in car["full_name"] for car in hits)


def test_search_endpoint_error_shape(client):
    response = client.post(
        "/api/cars/search",
        json={"filters": {"horsepower_min": 500, "horsepower_max": 400}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILTER"
    assert "cannot be greater than" in response.json()["error"]["message"]


def test_unknown_filter_field_is_rejected_by_the_api(client):
    response = client.post(
        "/api/cars/search", json={"filters": {"totally_made_up": 1}}
    )
    assert response.status_code == 422


def test_limit_is_enforced(client):
    response = client.post("/api/cars/search", json={"filters": {}, "limit": 5000})
    assert response.status_code == 422


def test_compare_preserves_order_and_reports_missing(client):
    listed = client.get("/api/cars", params={"limit": 3}).json()["results"]
    ids = [car["id"] for car in listed]
    body = client.post(
        "/api/compare", json={"car_ids": [*ids, "does-not-exist-0000"]}
    ).json()
    assert [car["id"] for car in body["results"]] == ids
    assert body["missing_ids"] == ["does-not-exist-0000"]


def test_chat_endpoint_returns_structured_rows_not_prose(client):
    body = client.post(
        "/api/chat", json={"message": "AWD cars under 90k with around 450 hp"}
    ).json()
    assert isinstance(body["results"], list)
    assert body["filters"]["drivetrain"] == ["AWD"]
    assert body["interpretations"]
    # The frontend must be able to ignore the prose entirely.
    assert body["conversation"]["active_filters"]["price_cr_max"] == 90000
