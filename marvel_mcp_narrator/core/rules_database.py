"""Rulebook database search utilities backed by local JSON data."""

from __future__ import annotations

import json
from threading import Lock
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


class RulesDatabase:
    """In-memory query interface for mechanics and powers."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._data = load_rules_database(path)

    def query_rules(self, query: str) -> str:
        """Search mechanics and powers by keyword and return markdown results."""
        keyword = query.strip().lower()
        if not keyword:
            return "Please provide a keyword to search the rulebook."

        mechanics_matches: list[dict[str, Any]] = []
        for key, payload in self._data.get("mechanics", {}).items():
            title = str(payload.get("title", key))
            category = str(payload.get("category", "Mechanics"))
            description = str(payload.get("description", ""))
            haystack = " ".join([key, title, category, description]).lower()
            if keyword in haystack:
                mechanics_matches.append(
                    {
                        "key": key,
                        "title": title,
                        "category": category,
                        "description": description,
                    }
                )

        powers_matches: list[dict[str, Any]] = []
        for payload in self._data.get("powers", []):
            name = str(payload.get("name", "Unknown Power"))
            category = str(payload.get("category", "Uncategorized"))
            rank_required = payload.get("rank_required", "?")
            description = str(payload.get("description", ""))
            haystack = " ".join([name, category, str(rank_required), description]).lower()
            if keyword in haystack:
                powers_matches.append(
                    {
                        "name": name,
                        "category": category,
                        "rank_required": rank_required,
                        "description": description,
                    }
                )

        if not mechanics_matches and not powers_matches:
            return f"No rulebook matches found for '{query}'."

        lines = [f"## Rulebook Search Results for `{query}`"]

        if mechanics_matches:
            lines.append("\n### Mechanics")
            for item in mechanics_matches:
                lines.append(f"- **{item['title']}** (`{item['key']}`)")
                lines.append(f"  - Category: {item['category']}")
                lines.append(f"  - {item['description']}")

        if powers_matches:
            lines.append("\n### Powers")
            for item in powers_matches:
                lines.append(f"- **{item['name']}**")
                lines.append(f"  - Category: {item['category']}")
                lines.append(f"  - Rank Required: {item['rank_required']}")
                lines.append(f"  - {item['description']}")

        return "\n".join(lines)


_DEFAULT_RULES_DATABASE: RulesDatabase | None = None
_DEFAULT_RULES_DATABASE_LOCK = Lock()


def query_rulebook_database(query: str) -> str:
    """Query the local rulebook database with a keyword search."""
    global _DEFAULT_RULES_DATABASE
    if _DEFAULT_RULES_DATABASE is None:
        with _DEFAULT_RULES_DATABASE_LOCK:
            if _DEFAULT_RULES_DATABASE is None:
                _DEFAULT_RULES_DATABASE = RulesDatabase()
    return _DEFAULT_RULES_DATABASE.query_rules(query)


def lookup_rule_reference(rule_key: str, path: Path | str | None = None) -> dict[str, Any]:
    """Backward-compatible exact lookup by mechanic key or power name."""
    normalized = rule_key.strip().lower()
    rules = load_rules_database(path)
    mechanics = rules.get("mechanics", {})
    normalized_mechanics = {str(key).lower(): (str(key), value) for key, value in mechanics.items()}

    if normalized in normalized_mechanics:
        original_key, payload = normalized_mechanics[normalized]
        if isinstance(payload, dict):
            return {"rule_key": original_key, "entry_type": "mechanic", **payload}
        return {"rule_key": original_key, "entry_type": "mechanic", "text": str(payload)}

    for power in rules.get("powers", []):
        power_name = str(power.get("name", "")).strip()
        if not power_name:
            continue
        power_normalized = power_name.lower()
        power_slug = power_normalized.replace(" ", "_")
        if normalized in {power_normalized, power_slug}:
            if isinstance(power, dict):
                return {"rule_key": power_slug, "entry_type": "power", **power}
            return {"rule_key": power_slug, "entry_type": "power", "text": str(power)}

    raise RulesLookupError(f"No rule reference found for '{rule_key}'.")
