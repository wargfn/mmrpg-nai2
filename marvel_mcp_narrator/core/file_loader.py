"""Unified RAG-style file and memory loading for session context injection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from marvel_mcp_narrator.core.character_state import CharacterRoster, character_roster
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase, get_campaign_database

NOTEBOOK_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}
DEFAULT_NOTEBOOK_DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "notebooks"
DEFAULT_DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
MAX_CONTEXT_BLOCKS = 6
MAX_NOTEBOOK_EXCERPT = 700
MAX_AUTOMATED_RULE_CITATIONS = 3
MAX_AUTOMATED_NOTEBOOK_CITATIONS = 2


def _normalize_query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9'_-]*", query.casefold()) if len(token) > 2]


def _normalize_phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))


class UnifiedContextInjector:
    """Load local files and session memory into structured prompt context blocks."""

    def __init__(
        self,
        *,
        campaign_database: CampaignDatabase | None = None,
        character_roster_store: CharacterRoster | None = None,
        data_directory: Path | str | None = None,
        notebook_directory: Path | str | None = None,
    ) -> None:
        self.campaign_database = campaign_database or get_campaign_database()
        self.character_roster = character_roster_store or character_roster
        self.data_directory = Path(data_directory) if data_directory is not None else DEFAULT_DATA_DIRECTORY
        self.notebook_directory = Path(notebook_directory) if notebook_directory is not None else DEFAULT_NOTEBOOK_DIRECTORY

    def load_local_json_files(self) -> dict[str, Any]:
        """Load JSON files from the local data directory."""
        payload: dict[str, Any] = {}
        if not self.data_directory.exists():
            return payload
        for path in sorted(self.data_directory.rglob("*.json")):
            if not path.is_file():
                continue
            try:
                payload[str(path.relative_to(self.data_directory))] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        return payload

    def load_notebook_sources(self) -> dict[str, str]:
        """Load markdown or text notebook exports from the notebook directory."""
        payload: dict[str, str] = {}
        if not self.notebook_directory.exists():
            return payload
        for path in sorted(self.notebook_directory.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in NOTEBOOK_EXTENSIONS:
                continue
            try:
                payload[str(path.relative_to(self.notebook_directory))] = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
        return payload

    def scan_prompt_for_keywords(self, query: str) -> dict[str, list[dict[str, str]]]:
        """Aggressively scan a prompt for rules and notebook keyword hits."""
        query_text = str(query).strip()
        if not query_text:
            return {"rules": [], "notebooks": []}

        normalized_query = _normalize_phrase(query_text)
        tokens = _normalize_query_tokens(query_text)
        return {
            "rules": self._match_rule_citations(normalized_query, tokens),
            "notebooks": self._match_notebook_citations(normalized_query, tokens),
        }

    def build_context_block(self, query: str) -> str:
        """Return structured context blocks relevant to the current user prompt."""
        query_text = str(query).strip()
        if not query_text:
            return ""

        tokens = _normalize_query_tokens(query_text)
        blocks: list[str] = []
        matches = self.scan_prompt_for_keywords(query_text)
        blocks.extend(match["block"] for match in matches["rules"])
        blocks.extend(match["block"] for match in matches["notebooks"])

        character_block = self._character_context(tokens)
        if character_block:
            blocks.append(character_block)

        campaign_block = self._campaign_context(tokens)
        if campaign_block:
            blocks.append(campaign_block)

        return "\n\n".join(blocks[:MAX_CONTEXT_BLOCKS])

    def _match_rule_citations(self, normalized_query: str, tokens: list[str]) -> list[dict[str, str]]:
        matches: list[dict[str, str]] = []
        seen_titles: set[str] = set()
        for record in self._iter_rule_records():
            matched_alias = self._find_matching_alias(normalized_query, record["aliases"])
            if matched_alias is None:
                continue
            title = record["title"]
            if title.casefold() in seen_titles:
                continue
            seen_titles.add(title.casefold())
            matches.append(
                {
                    "title": title,
                    "matched_alias": matched_alias,
                    "block": self._format_rule_citation_block(title, record["exact_text"]),
                }
            )
            if len(matches) >= MAX_AUTOMATED_RULE_CITATIONS:
                break
        return matches

    def _match_notebook_citations(self, normalized_query: str, tokens: list[str]) -> list[dict[str, str]]:
        matches: list[dict[str, str]] = []
        for record in self._iter_notebook_records():
            matched_alias = self._find_matching_alias(normalized_query, record["aliases"])
            if matched_alias is None and not any(token in record["content_normalized"] for token in tokens if len(token) > 3):
                continue
            exact_text = self._extract_notebook_exact_text(record["content"], tokens)
            matches.append(
                {
                    "title": record["title"],
                    "matched_alias": matched_alias or record["title"],
                    "block": self._format_notebook_citation_block(record["title"], exact_text),
                }
            )
            if len(matches) >= MAX_AUTOMATED_NOTEBOOK_CITATIONS:
                break
        return matches

    def _iter_rule_records(self) -> list[dict[str, Any]]:
        json_files = self.load_local_json_files()
        rules_payload = json_files.get("rules.json")
        if not isinstance(rules_payload, dict):
            return []

        records: list[dict[str, Any]] = []

        mechanics = rules_payload.get("mechanics", {})
        if isinstance(mechanics, dict):
            for key, payload in mechanics.items():
                if not isinstance(payload, dict):
                    continue
                title = str(payload.get("title", key)).strip() or str(key)
                aliases = {str(key), title, str(key).replace("_", " ")}
                records.append(
                    self._make_rule_record(
                        title=title,
                        aliases=aliases,
                        exact_payload=payload,
                        priority=0,
                    )
                )

        powers = rules_payload.get("powers", [])
        if isinstance(powers, list):
            for payload in powers:
                if not isinstance(payload, dict):
                    continue
                title = str(payload.get("name", "")).strip()
                if not title:
                    continue
                records.append(
                    self._make_rule_record(
                        title=title,
                        aliases={title},
                        exact_payload=payload,
                        priority=2,
                    )
                )

        power_sets = rules_payload.get("power_sets", [])
        if isinstance(power_sets, list):
            family_entries: dict[str, list[dict[str, Any]]] = {}
            for power_set in power_sets:
                if not isinstance(power_set, dict):
                    continue
                set_name = str(power_set.get("name", "")).strip()
                if set_name:
                    records.append(
                        self._make_rule_record(
                            title=set_name,
                            aliases={set_name},
                            exact_payload=power_set,
                            priority=1,
                        )
                    )
                for payload in power_set.get("powers", []):
                    if not isinstance(payload, dict):
                        continue
                    power_name = str(payload.get("name", "")).strip()
                    if not power_name:
                        continue
                    exact_payload = {"power_set": set_name, **payload} if set_name else dict(payload)
                    family_name = self._family_alias(power_name)
                    if family_name:
                        family_entries.setdefault(family_name.casefold(), []).append(exact_payload)
                    records.append(
                        self._make_rule_record(
                            title=power_name,
                            aliases={power_name},
                            exact_payload=exact_payload,
                            priority=2,
                        )
                    )
            for family_name, entries in family_entries.items():
                if len(entries) < 2:
                    continue
                title = entries[0]["name"].rsplit(" ", 1)[0]
                records.append(
                    self._make_rule_record(
                        title=title,
                        aliases={title},
                        exact_payload=entries,
                        priority=1,
                    )
                )

        return sorted(
            records,
            key=lambda record: (
                record["priority"],
                -record["longest_alias_length"],
                record["title"].casefold(),
            ),
        )

    def _iter_notebook_records(self) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        for name, content in self.load_notebook_sources().items():
            title = Path(name).stem
            aliases = {title, name}
            aliases.update(self._markdown_headings(content))
            records.append(
                {
                    "title": name,
                    "content": content,
                    "content_normalized": _normalize_phrase(content),
                    "aliases": {alias for alias in aliases if str(alias).strip()},
                }
            )
        return records

    @staticmethod
    def _make_rule_record(
        *,
        title: str,
        aliases: set[str],
        exact_payload: Any,
        priority: int,
    ) -> dict[str, Any]:
        normalized_aliases = {_normalize_phrase(alias) for alias in aliases if _normalize_phrase(alias)}
        return {
            "title": title,
            "aliases": normalized_aliases,
            "longest_alias_length": max((len(alias) for alias in normalized_aliases), default=0),
            "exact_text": json.dumps(exact_payload, ensure_ascii=False, indent=2),
            "priority": priority,
        }

    @staticmethod
    def _family_alias(power_name: str) -> str | None:
        match = re.fullmatch(r"(.+?)\s+\d+", power_name.strip())
        if match is None:
            return None
        return match.group(1).strip() or None

    @staticmethod
    def _markdown_headings(content: str) -> set[str]:
        headings: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                headings.add(stripped.lstrip("#").strip())
        return headings

    @staticmethod
    def _find_matching_alias(normalized_query: str, aliases: set[str]) -> str | None:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias and alias in normalized_query:
                return alias
        return None

    @staticmethod
    def _format_rule_citation_block(title: str, exact_text: str) -> str:
        return f"[System Context - Automated Rule Citation: {title}]\n{exact_text}"

    @staticmethod
    def _format_notebook_citation_block(title: str, exact_text: str) -> str:
        return f"[System Context - Automated Notebook Citation: {title}]\n{exact_text}"

    @staticmethod
    def _extract_notebook_exact_text(content: str, tokens: list[str]) -> str:
        stripped = content.strip()
        if len(stripped) <= MAX_NOTEBOOK_EXCERPT:
            return stripped

        lowered = stripped.casefold()
        first_index = min((lowered.find(token.casefold()) for token in tokens if lowered.find(token.casefold()) >= 0), default=-1)
        if first_index < 0:
            return stripped[:MAX_NOTEBOOK_EXCERPT].rstrip()

        start = max(0, first_index - 150)
        end = min(len(stripped), first_index + MAX_NOTEBOOK_EXCERPT - 150)
        excerpt = stripped[start:end].strip()
        if start > 0:
            excerpt = "…" + excerpt
        if end < len(stripped):
            excerpt = excerpt + "…"
        return excerpt

    def _character_context(self, tokens: list[str]) -> str:
        active_sheet = self.character_roster.get_active_sheet()
        candidate_sheets: list[dict[str, Any]] = []
        if active_sheet is not None:
            candidate_sheets.append(active_sheet)
        sheets = self._all_character_sheets()
        for sheet in sheets:
            if active_sheet is not None and sheet.get("name") == active_sheet.get("name"):
                continue
            candidate_sheets.append(sheet)

        matches = []
        for sheet in candidate_sheets:
            haystack = " ".join(
                [
                    str(sheet.get("name", "")),
                    str(sheet.get("archetype", "")),
                    " ".join(str(tag) for tag in sheet.get("tags", [])),
                    " ".join(str(trait) for trait in sheet.get("traits", [])),
                ]
            ).casefold()
            if any(token in haystack for token in tokens):
                matches.append(sheet)
        if not matches:
            return ""

        lines = ["Relevant Character Sheets:"]
        for sheet in matches[:2]:
            derived_stats = sheet.get("derived_stats", {})
            lines.append(
                (
                    f"- {sheet['name']} ({sheet['archetype']}, Rank {sheet['rank']}): "
                    f"Melee {sheet['melee']}, Agility {sheet['agility']}, Resilience {sheet['resilience']}, "
                    f"Vigilance {sheet['vigilance']}, Ego {sheet['ego']}, Logic {sheet['logic']}; "
                    f"Health {derived_stats.get('max_health', sheet.get('max_health'))}, "
                    f"Focus {derived_stats.get('max_focus', sheet.get('max_focus'))}."
                )
            )
        return "\n".join(lines)

    def _campaign_context(self, tokens: list[str]) -> str:
        lines: list[str] = []
        previous_summary = self.campaign_database.get_previous_campaign_events_summary()
        if previous_summary:
            lines.append(f"- Previous events: {previous_summary}")

        campaign_context = self.campaign_database.get_current_session_context()
        if campaign_context is not None:
            session = campaign_context.get("session", {})
            searchable = " ".join(
                [
                    str(campaign_context.get("theme", "")),
                    str(campaign_context.get("villain", "")),
                    str(session.get("title", "")),
                    " ".join(str(item) for item in session.get("objectives", [])),
                    " ".join(str(item) for item in session.get("key_npcs", [])),
                    " ".join(str(item) for item in session.get("locations", [])),
                ]
            ).casefold()
            if any(token in searchable for token in tokens):
                lines.append(
                    (
                        f"- Active campaign: {campaign_context['theme']} vs {campaign_context['villain']}; "
                        f"Session {campaign_context['active_session_number']} '{session.get('title', '')}' "
                        f"Objectives: {', '.join(str(item) for item in session.get('objectives', [])) or 'None'}."
                    )
                )

        seen_summaries: set[str] = set()
        for token in tokens:
            for entry in self.campaign_database.search_memory_records(token, limit=2):
                summary = str(entry["summary"]).strip()
                if not summary or summary in seen_summaries:
                    continue
                seen_summaries.add(summary)
                lines.append(f"- Memory match ({entry['memory_type']}): {summary}")
                if len(lines) >= 4:
                    break
            if len(lines) >= 4:
                break

        if not lines:
            return ""
        return "\n".join(["Relevant Campaign Context:", *lines[:4]])

    def _all_character_sheets(self) -> list[dict[str, Any]]:
        list_sheets = getattr(self.character_roster, "list_sheets", None)
        if callable(list_sheets):
            return list_sheets()
        return []
