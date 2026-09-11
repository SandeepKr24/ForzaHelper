"""Constraint extraction, tolerance policy, and malformed LLM output."""

from __future__ import annotations

import pytest

from forzahelper.chat.extraction import LangChainExtractor, RuleBasedExtractor
from forzahelper.config import Settings
from forzahelper.interpret import apply_tolerance
from forzahelper.models import CarFilters


@pytest.fixture
def extractor():
    return RuleBasedExtractor()


def test_doc_example_request(extractor):
    filters = extractor.extract(
        "I want a car built 2000 or later, under 90k CR, AWD stock, "
        "and around 450 HP.",
        CarFilters(),
    )
    assert filters.year_min == 2000
    assert filters.price_cr_max == 90000
    assert filters.drivetrain == ["AWD"]
    assert filters.horsepower_target == 450
    # "around" must not become an exact match (doc section 12).
    assert filters.horsepower_min is None
    assert filters.horsepower_max is None


def test_follow_up_narrows_rather_than_replaces(extractor):
    """Doc section 17: the second message modifies the existing constraints."""
    first = extractor.extract("Find AWD cars under 100k with around 500 hp.", CarFilters())
    second = extractor.extract("What about only Japanese cars?", first)

    assert second.country == ["Japan"]
    assert second.price_cr_max == 100000
    assert second.drivetrain == ["AWD"]
    assert second.horsepower_target == 500


def test_reset_clears_previous_constraints(extractor):
    first = extractor.extract("AWD cars under 100k", CarFilters())
    second = extractor.extract("start over, show me S1 class cars", first)
    assert second.price_cr_max is None
    assert second.drivetrain is None
    assert second.pi_class == ["S1"]


def test_vague_words_do_not_invent_thresholds(extractor):
    """Doc section 15: never silently assume a CR value."""
    filters = extractor.extract("something cheap and fast", CarFilters())
    assert filters.active() == {}


@pytest.mark.parametrize(
    "message,expected",
    [
        ("rear wheel drive only", ["RWD"]),
        ("front-wheel drive hatchbacks", ["FWD"]),
        ("4wd please", ["AWD"]),
        ("quattro", ["AWD"]),
    ],
)
def test_drivetrain_synonyms(extractor, message, expected):
    assert extractor.extract(message, CarFilters()).drivetrain == expected


@pytest.mark.parametrize(
    "message,expected",
    [
        ("japanese cars", ["Japan"]),
        ("jdm legends", ["Japan"]),
        ("german or italian", ["Germany", "Italy"]),
        ("british classics", ["UK"]),
    ],
)
def test_country_synonyms(extractor, message, expected):
    assert extractor.extract(message, CarFilters()).country == expected


@pytest.mark.parametrize(
    "message,lo,hi",
    [
        ("between 300 and 400 hp", 300, 400),
        ("at least 600 horsepower", 600, None),
        ("under 200 hp", None, 200),
    ],
)
def test_explicit_horsepower_bounds(extractor, message, lo, hi):
    filters = extractor.extract(message, CarFilters())
    assert filters.horsepower_min == lo
    assert filters.horsepower_max == hi
    assert filters.horsepower_target is None


def test_price_suffixes(extractor):
    assert extractor.extract("under 90k", CarFilters()).price_cr_max == 90000
    assert extractor.extract("under 1.5m", CarFilters()).price_cr_max == 1_500_000


# ------------------------------------------------------------------ tolerance


def test_around_expands_to_ten_percent():
    filters, notes = apply_tolerance(CarFilters(horsepower_target=450))
    assert (filters.horsepower_min, filters.horsepower_max) == (405, 495)
    assert notes == ["Around 450 HP was interpreted as 405-495 HP (+/-10%)."]


def test_tolerance_is_announced_not_silent():
    _, notes = apply_tolerance(CarFilters(horsepower_target=500))
    assert notes and "450-550" in notes[0]


def test_explicit_bounds_win_over_target():
    filters, notes = apply_tolerance(
        CarFilters(horsepower_target=450, horsepower_min=440, horsepower_max=460)
    )
    assert (filters.horsepower_min, filters.horsepower_max) == (440, 460)
    assert "ranking preference" in notes[0]


def test_minimum_absolute_tolerance_applies_to_small_targets():
    """10% of 20 HP is 2 HP, which is uselessly narrow."""
    settings = Settings(default_tolerance_pct=0.10, min_tolerance_abs=5.0)
    filters, _ = apply_tolerance(CarFilters(horsepower_target=20), settings)
    assert (filters.horsepower_min, filters.horsepower_max) == (15, 25)


def test_tolerance_never_produces_negative_horsepower():
    settings = Settings(default_tolerance_pct=0.10, min_tolerance_abs=50.0)
    filters, _ = apply_tolerance(CarFilters(horsepower_target=10), settings)
    assert filters.horsepower_min == 0


def test_no_target_is_a_no_op():
    original = CarFilters(year_min=2000)
    filters, notes = apply_tolerance(original)
    assert filters == original
    assert notes == []


# ------------------------------------------------------- malformed LLM output


class _BrokenModel:
    """Stands in for a model returning something that fails validation."""

    def __init__(self, payload):
        self.payload = payload

    def invoke(self, _messages):
        return self.payload


class _RejectsTemperature:
    """Mimics a model generation where sampling parameters were removed."""

    def __init__(self):
        self.calls = 0

    def invoke(self, _prompt):
        self.calls += 1
        raise RuntimeError(
            "Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': '`temperature` is deprecated "
            "for this model.'}}"
        )


def test_model_rejecting_temperature_is_retried_not_abandoned(monkeypatch):
    """A model that refuses sampling params must still be used.

    Falling back here would silently downgrade every request to the rule-based
    extractor while looking like it worked.
    """
    extractor = LangChainExtractor(Settings(llm_model="fake", llm_provider="anthropic"))
    built = []

    def fake_build():
        built.append(extractor._use_temperature)
        if extractor._use_temperature:
            return _RejectsTemperature()
        return _BrokenModel({"country": ["Japan"], "price_cr_max": 100000})

    monkeypatch.setattr(extractor, "_build_model", fake_build)

    result = extractor.extract("japanese cars under 100k", CarFilters())

    # Built once with temperature, rebuilt once without after the 400.
    assert built == [True, False]
    assert extractor._use_temperature is False
    # The real model's answer was used, not the rule-based fallback.
    assert result.country == ["Japan"]
    assert result.price_cr_max == 100000


def test_temperature_is_dropped_permanently_after_the_first_rejection(monkeypatch):
    extractor = LangChainExtractor(Settings(llm_model="fake"))
    extractor._use_temperature = False
    extractor._model = _BrokenModel({"drivetrain": ["RWD"]})

    assert extractor.extract("rwd", CarFilters()).drivetrain == ["RWD"]
    assert extractor._use_temperature is False


@pytest.mark.parametrize(
    "payload",
    [
        {"horsepower_min": 900, "horsepower_max": 100},  # inverted range
        {"year_min": "not a year"},
        {"made_up_field": 1},
        {"price_cr_max": -5},
        None,
        "just some prose",
    ],
)
def test_malformed_model_output_falls_back_instead_of_raising(payload):
    """Invalid structured output must never reach the query builder."""
    extractor = LangChainExtractor(Settings(llm_model="fake"))
    extractor._model = _BrokenModel(payload)

    result = extractor.extract("AWD cars under 90k", CarFilters())

    # Fell back to the rule-based parser, and the result is a valid CarFilters.
    assert isinstance(result, CarFilters)
    assert result.price_cr_max == 90000
    assert result.drivetrain == ["AWD"]
