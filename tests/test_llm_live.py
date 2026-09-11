"""Live LLM extraction tests.

Skipped by default because they make real, billed API calls. Run with:

    FH_LIVE_LLM=1 uv run pytest tests/test_llm_live.py -v

These cover what the rule-based extractor cannot do -- understanding phrasing
it has no pattern for -- so a pass here proves the model was actually reached
rather than the fallback silently answering.
"""

from __future__ import annotations

import os

import pytest

from forzahelper.chat.extraction import LangChainExtractor, RuleBasedExtractor
from forzahelper.config import get_settings
from forzahelper.models import CarFilters

pytestmark = pytest.mark.skipif(
    os.environ.get("FH_LIVE_LLM") != "1",
    reason="live LLM tests cost money; set FH_LIVE_LLM=1 to run",
)


@pytest.fixture(scope="module")
def extractor():
    settings = get_settings()
    if not settings.llm_model:
        pytest.skip("no FH_LLM_MODEL configured")
    return LangChainExtractor(settings)


def test_model_is_actually_reached_not_the_fallback(extractor):
    """Numbers written as words defeat the regex extractor."""
    message = (
        "Show me Japanese all-wheel-drive machines that cost less than "
        "a hundred thousand credits and make roughly six hundred horsepower"
    )
    assert RuleBasedExtractor().extract(message, CarFilters()).active() == {
        "country": ["Japan"]
    }

    filters = extractor.extract(message, CarFilters())
    assert filters.country == ["Japan"]
    assert filters.drivetrain == ["AWD"]
    assert filters.price_cr_max == 100_000
    # "roughly" is a target, so the tolerance policy owns the range.
    assert filters.horsepower_target == 600
    assert filters.horsepower_min is None


def test_model_does_not_invent_thresholds_for_vague_words(extractor):
    filters = extractor.extract("something cheap and really quick", CarFilters())
    assert filters.price_cr_max is None
    assert filters.horsepower_min is None
    assert filters.horsepower_target is None


def test_model_preserves_prior_constraints_on_follow_up(extractor):
    first = extractor.extract(
        "AWD cars under 100k with around 500 hp", CarFilters()
    )
    second = extractor.extract("actually, make it Italian only", first)
    assert second.country == ["Italy"]
    assert second.drivetrain == ["AWD"]
    assert second.price_cr_max == 100_000
    assert second.horsepower_target == 500


def test_extraction_is_reproducible(extractor):
    message = "German RWD cars from 2010 onwards under 250k"
    runs = [extractor.extract(message, CarFilters()).active() for _ in range(2)]
    assert runs[0] == runs[1]
