"""Rule lookup utilities backed by local JSON data."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any


class RulesLookupError(LookupError):
    """Raised when a requested rule cannot be found."""


def load_rules_database(path: Path | str | None = None) -> dict[str, Any]:
    """Load and return the rule database JSON payload."""
    if path is not None:
        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    content = files("marvel_mcp_narrator.data").joinpath("rules.json").read_text(encoding="utf-8")
    return json.loads(content)


def lookup_rule_reference(rule_key: str, path: Path | str | None = None) -> dict[str, Any]:
    """Look up a rule key from the local JSON rule database."""
    normalized = rule_key.strip().lower()
    rules = load_rules_database(path)
    references = rules.get("references", {})

    if normalized not in references:
        raise RulesLookupError(f"No rule reference found for '{rule_key}'.")

    payload = references[normalized]
    if isinstance(payload, dict):
        return {"rule_key": normalized, **payload}

    return {"rule_key": normalized, "text": str(payload)}
