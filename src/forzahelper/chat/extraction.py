"""Natural language -> CarFilters.

The extractor is the only place an LLM is involved in deciding *what* to search
for, and its output is validated by Pydantic before anything touches the
database. It never emits SQL (doc sections 10 and 23).

Two implementations share one interface:

  * `LangChainExtractor` -- a real model, via LangChain structured output.
  * `RuleBasedExtractor`  -- a deterministic parser covering the common phrasings.

The rule-based one is not a toy stub: it keeps the whole pipeline, the tests and
local development working with no API key and no network call, and it is the
fallback when the model is unavailable or returns something invalid.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from ..config import Settings, get_settings
from ..models import CarFilters

logger = logging.getLogger(__name__)


class ConstraintExtractor(Protocol):
    """Turns a message plus the conversation's current filters into new filters."""

    def extract(self, message: str, current: CarFilters) -> CarFilters: ...

_COUNTRY_SYNONYMS = {
    "japanese": "Japan",
    "jdm": "Japan",
    "japan": "Japan",
    "german": "Germany",
    "germany": "Germany",
    "italian": "Italy",
    "italy": "Italy",
    "american": "USA",
    "america": "USA",
    "usa": "USA",
    "us": "USA",
    "british": "UK",
    "britain": "UK",
    "uk": "UK",
    "english": "UK",
    "french": "France",
    "france": "France",
    "korean": "Korea",
    "korea": "Korea",
    "swedish": "Sweden",
    "sweden": "Sweden",
    "australian": "Australia",
    "australia": "Australia",
    "chinese": "China",
    "china": "China",
}

_DRIVETRAIN_SYNONYMS = {
    "awd": "AWD",
    "4wd": "AWD",
    "four wheel drive": "AWD",
    "all wheel drive": "AWD",
    "all-wheel drive": "AWD",
    "quattro": "AWD",
    "rwd": "RWD",
    "rear wheel drive": "RWD",
    "rear-wheel drive": "RWD",
    "fwd": "FWD",
    "front wheel drive": "FWD",
    "front-wheel drive": "FWD",
}

_MULTIPLIERS = {"k": 1_000, "m": 1_000_000}


def _parse_amount(number: str, suffix: str | None) -> int:
    value = float(number.replace(",", ""))
    if suffix:
        value *= _MULTIPLIERS[suffix.lower()]
    return int(value)


class RuleBasedExtractor:
    """Deterministic parser for the common request shapes.

    Returns a *delta* merged onto the current filters, so follow-up turns such
    as "only Japanese cars" narrow the existing search rather than replacing it
    (doc section 17).
    """

    _RESET_PATTERN = re.compile(
        r"\b(start over|reset|clear (the )?filters|new search|forget that)\b", re.I
    )

    def extract(self, message: str, current: CarFilters) -> CarFilters:
        text = message.lower()
        if self._RESET_PATTERN.search(text):
            current = CarFilters()

        update: dict[str, object] = {}

        m = re.search(
            r"(?:under|below|less than|cheaper than|max(?:imum)?|up to|within)\s*"
            r"(?:cr\s*)?\$?([\d,.]+)\s*([km])?\b",
            text,
        )
        if m:
            update["price_cr_max"] = _parse_amount(m.group(1), m.group(2))
        m = re.search(
            r"(?:over|above|more than|at least|min(?:imum)?)\s*(?:cr\s*)?\$?"
            r"([\d,.]+)\s*([km])?\s*(?:cr|credits?)\b",
            text,
        )
        if m:
            update["price_cr_min"] = _parse_amount(m.group(1), m.group(2))

        m = re.search(
            r"(?:around|about|roughly|approx(?:imately)?|near|~)\s*([\d,.]+)\s*"
            r"([km])?\s*(?:hp|horsepower|bhp)",
            text,
        )
        if m:
            update["horsepower_target"] = _parse_amount(m.group(1), m.group(2))
        else:
            m = re.search(
                r"(?:between)\s*([\d,.]+)\s*(?:and|-|to)\s*([\d,.]+)\s*"
                r"(?:hp|horsepower|bhp)",
                text,
            )
            if m:
                update["horsepower_min"] = _parse_amount(m.group(1), None)
                update["horsepower_max"] = _parse_amount(m.group(2), None)
            else:
                m = re.search(
                    r"(?:at least|over|above|more than|min(?:imum)?)\s*([\d,.]+)\s*"
                    r"([km])?\s*(?:hp|horsepower|bhp)",
                    text,
                )
                if m:
                    update["horsepower_min"] = _parse_amount(m.group(1), m.group(2))
                m = re.search(
                    r"(?:under|below|less than|max(?:imum)?)\s*([\d,.]+)\s*"
                    r"([km])?\s*(?:hp|horsepower|bhp)",
                    text,
                )
                if m:
                    update["horsepower_max"] = _parse_amount(m.group(1), m.group(2))

        # --- year --------------------------------------------------------
        m = re.search(
            r"\b(?:from|after|since|newer than|built)?\s*(\d{4})\s*"
            r"(?:or later|or newer|\+|onwards?)\b",
            text,
        )
        if m:
            update["year_min"] = int(m.group(1))
        m = re.search(r"\b(?:before|older than|up to|until)\s*(\d{4})\b", text)
        if m:
            update["year_max"] = int(m.group(1))
        m = re.search(r"\bbetween\s*(\d{4})\s*(?:and|-|to)\s*(\d{4})\b", text)
        if m:
            update["year_min"] = int(m.group(1))
            update["year_max"] = int(m.group(2))

        # --- drivetrain --------------------------------------------------
        drivetrains = {
            canonical
            for phrase, canonical in _DRIVETRAIN_SYNONYMS.items()
            if re.search(rf"\b{re.escape(phrase)}\b", text)
        }
        if drivetrains:
            update["drivetrain"] = sorted(drivetrains)

        # --- country -----------------------------------------------------
        countries = {
            canonical
            for word, canonical in _COUNTRY_SYNONYMS.items()
            if re.search(rf"\b{re.escape(word)}\b", text)
        }
        if countries:
            update["country"] = sorted(countries)

        # --- PI class ----------------------------------------------------
        classes = re.findall(r"\b(?:class\s+)?(s1|s2|[abcdr])\s+class\b", text)
        classes += re.findall(r"\bclass\s+(s1|s2|[abcdr])\b", text)
        if classes:
            update["pi_class"] = sorted({c.upper() for c in classes})

        return current.model_copy(update=update)


_SYSTEM_PROMPT = """\
You convert a Forza Horizon 6 car request into structured search filters.

You are given the filters already active in this conversation. Return the
COMPLETE updated filter set: keep constraints the user has not changed, apply
the ones they just asked for, and drop only what they explicitly removed.

Rules:
- Only use the fields in the schema. Never write SQL.
- Use null for anything the user did not constrain. Never invent a value.
- "around N hp" / "about N hp" -> set horsepower_target to N and leave
  horsepower_min and horsepower_max null. A tolerance is applied downstream.
  Only set horsepower_min/max when the user gives an explicit bound or range.
- Prices are in in-game credits (CR). "90k" means 90000.
- Map nationalities to the country values listed below (e.g. "Japanese" ->
  "Japan"), and drivetrain words to the drivetrain values ("all wheel drive"
  -> "AWD").
- Vague words such as "cheap", "fast" or "good" have no numeric meaning. Do NOT
  guess a threshold for them -- leave the relevant field null.
- If the user names a country, make, type or class that is NOT in the lists
  below, record it anyway, exactly as they wrote it. Never drop a constraint
  because its value is unfamiliar: returning no cars is the correct answer to a
  request the data cannot satisfy, and quietly ignoring part of the request is
  not. This is different from a vague word, which constrains nothing at all.

Valid values currently present in the database:
{vocabulary}
"""


class LangChainExtractor:
    """Structured-output extraction through LangChain.

    Any failure -- no credentials, a network error, or output that fails
    validation -- falls back to the rule-based extractor rather than failing the
    request or letting an unvalidated object through.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._fallback = RuleBasedExtractor()
        self._model = None
        self._use_temperature = True

    def _build_model(self):
        from langchain.chat_models import init_chat_model

        kwargs: dict[str, object] = {"max_tokens": self.settings.llm_max_tokens}
        if self._use_temperature:
            kwargs["temperature"] = 0
        if self.settings.llm_provider:
            kwargs["model_provider"] = self.settings.llm_provider
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key
        if self.settings.llm_timeout_s:
            kwargs["timeout"] = self.settings.llm_timeout_s

        model = init_chat_model(self.settings.llm_model, **kwargs)
        return model.with_structured_output(CarFilters)

    def _get_model(self):
        if self._model is None:
            self._model = self._build_model()
        return self._model

    @staticmethod
    def _is_unsupported_sampling_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "temperature" in text and (
            "deprecated" in text or "not supported" in text or "unsupported" in text
        )

    def _vocabulary(self) -> str:
        from ..search import filter_metadata

        meta = filter_metadata()["categorical"]
        lines = []
        for key in ("drivetrain", "pi_class", "country", "rarity", "acquisition_methods"):
            lines.append(f"- {key}: {', '.join(meta[key])}")
        lines.append(f"- car_type: {', '.join(meta['car_type'])}")
        lines.append(f"- make: {len(meta['make'])} manufacturers, matched exactly")
        return "\n".join(lines)

    def _prompt(self, message: str, current: CarFilters) -> list[tuple[str, str]]:
        return [
            ("system", _SYSTEM_PROMPT.format(vocabulary=self._vocabulary())),
            (
                "human",
                f"Currently active filters (JSON):\n"
                f"{current.model_dump_json(exclude_none=True)}\n\n"
                f"User message:\n{message}",
            ),
        ]

    def extract(self, message: str, current: CarFilters) -> CarFilters:
        prompt = self._prompt(message, current)
        try:
            try:
                result = self._get_model().invoke(prompt)
            except Exception as exc:
                if not (self._use_temperature and self._is_unsupported_sampling_error(exc)):
                    raise
                logger.info(
                    "%s rejects temperature; retrying without sampling parameters.",
                    self.settings.llm_model,
                )
                self._use_temperature = False
                self._model = self._build_model()
                result = self._model.invoke(prompt)

            return CarFilters.model_validate(
                result if isinstance(result, dict) else result.model_dump()
            )
        except Exception:
            logger.warning(
                "LLM constraint extraction failed; using rule-based fallback",
                exc_info=True,
            )
            return self._fallback.extract(message, current)


def get_extractor(settings: Settings | None = None) -> ConstraintExtractor:
    """Pick an extractor based on configuration.

    Without a configured model, the rule-based extractor is used, so the API is
    fully functional before any LLM credentials exist.
    """
    settings = settings or get_settings()
    if settings.llm_model:
        return LangChainExtractor(settings)
    logger.info("No FH_LLM_MODEL configured; using the rule-based extractor.")
    return RuleBasedExtractor()
