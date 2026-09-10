"""Rule lookup utilities backed by local JSON data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules.json"


class RulesLookupError(LookupError):
    """Raised when a requested rule cannot be found."""


def load_rules_database(path: Path | str | None = None) -> dict[str, Any]:
    """Load and return the rule database JSON payload."""
    source = Path(path) if path is not None else DEFAULT_RULES_PATH
    with source.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def lookup_rule_reference(rule_key: str, path: Path | str | None = None) -> dict[str, Any]:
    """Look up a rule key from the local JSON rule database."""
    normalized = rule_key.strip().lower()
    rules = load_rules_database(path)
    references = rules.get("references", {})

    if normalized not in references:
        raise RulesLookupError(f"No rule reference found for '{rule_key}'.")

    payload = references[normalized]
    if isinstance(payload, dict):
        return payload

    return {"text": str(payload)}
