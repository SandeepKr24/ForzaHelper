"""Car name suggestions for the table search: typo tolerance and the endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from forzahelper.api import app
from forzahelper.search import name_score, rank_suggestions

from .conftest import requires_db

CARS = [
    {"id": "lamborghini-huracan-sto-2021", "make": "Lamborghini", "model": "Huracán STO", "year": 2021},
    {"id": "lamborghini-huracan-evo-2020", "make": "Lamborghini", "model": "Huracán EVO", "year": 2020},
    {"id": "porsche-911-gt3-rs-2019", "make": "Porsche", "model": "911 GT3 RS", "year": 2019},
    {"id": "mazda-rx-7-spirit-r-type-a-2002", "make": "Mazda", "model": "RX-7 Spirit R Type A", "year": 2002},
    {"id": "mclaren-f1-1994", "make": "McLaren", "model": "F1", "year": 1994},
    {"id": "ferrari-f40-1987", "make": "Ferrari", "model": "F40", "year": 1987},
    {"id": "nissan-skyline-gt-r-v-spec-1993", "make": "Nissan", "model": "Skyline GT-R V-Spec", "year": 1993},
]


def names(query: str, limit: int = 2) -> list[str]:
    return [s["name"] for s in rank_suggestions(query, CARS, limit)]


# ------------------------------------------------------------------ ranking


def test_misspelled_make_and_model():
    # Equal matches of equal length: the newer car comes first.
    assert names("lamborgini huracn") == ["Lamborghini Huracán STO", "Lamborghini Huracán EVO"]


def test_misspelled_make_with_number():
    assert names("porshe 911")[0] == "Porsche 911 GT3 RS"


def test_single_misspelled_word():
    assert names("ferari")[0] == "Ferrari F40"


def test_accents_are_optional():
    assert names("huracan")[0].startswith("Lamborghini Huracán")


def test_partial_word_while_typing():
    assert names("mclar")[0] == "McLaren F1"


def test_missing_hyphen_or_space():
    assert names("rx7")[0] == "Mazda RX-7 Spirit R Type A"
    assert names("skyline gtr")[0] == "Nissan Skyline GT-R V-Spec"


def test_at_most_two_by_default():
    assert len(rank_suggestions("a", CARS)) <= 2
    assert len(names("lamborghini")) == 2


def test_nonsense_gives_nothing():
    assert names("xyzqwv") == []


def test_duplicate_names_are_shown_once():
    twice = CARS + [{**CARS[5], "id": "ferrari-f40-1990", "year": 1990}]
    ranked = rank_suggestions("ferrari f40", twice, limit=5)
    assert [s["name"] for s in ranked].count("Ferrari F40") == 1


def test_scores_are_between_zero_and_one():
    for query in ("lambo", "porshe", "zzz", ""):
        for car in CARS:
            assert 0.0 <= name_score(query, f"{car['make']} {car['model']}") <= 1.0


# ------------------------------------------------------------------ endpoint


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@requires_db
def test_endpoint_suggests_for_a_misspelling(client):
    response = client.get("/api/cars/suggest", params={"q": "ferari"})
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body["suggestions"]) <= 2
    assert body["suggestions"][0]["make"] == "Ferrari"


@requires_db
def test_endpoint_is_not_taken_for_a_car_id(client):
    # /api/cars/{car_id} must not swallow /api/cars/suggest.
    response = client.get("/api/cars/suggest", params={"q": "porsche"})
    assert response.status_code == 200
    assert "suggestions" in response.json()


@requires_db
def test_endpoint_rejects_an_empty_query(client):
    response = client.get("/api/cars/suggest", params={"q": ""})
    assert response.status_code in (400, 422)
    assert "error" in response.json()
