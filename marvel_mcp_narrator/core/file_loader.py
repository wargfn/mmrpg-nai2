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
MAX_CONTEXT_BLOCKS = 4
MAX_NOTEBOOK_EXCERPT = 500


def _normalize_query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9'_-]*", query.casefold()) if len(token) > 2]


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

    def build_context_block(self, query: str) -> str:
        """Return structured context blocks relevant to the current user prompt."""
        blocks: list[str] = []
        tokens = _normalize_query_tokens(query)
        if not tokens:
            return ""

        character_block = self._character_context(tokens)
        if character_block:
            blocks.append(character_block)

        rulebook_block = self._rulebook_context(query)
        if rulebook_block:
            blocks.append(rulebook_block)

        campaign_block = self._campaign_context(tokens)
        if campaign_block:
            blocks.append(campaign_block)

        notebook_block = self._notebook_context(tokens)
        if notebook_block:
            blocks.append(notebook_block)

        return "\n\n".join(blocks[:MAX_CONTEXT_BLOCKS])

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

    def _rulebook_context(self, query: str) -> str:
        json_files = self.load_local_json_files()
        rules_payload = json_files.get("rules.json")
        if not isinstance(rules_payload, dict):
            return ""
        query_text = query.casefold()
        matched_entries: list[str] = []
        for section_name, section_payload in rules_payload.items():
            if not isinstance(section_payload, dict):
                continue
            for entry_name, entry_payload in section_payload.items():
                if len(matched_entries) >= 3:
                    break
                serialized_entry = json.dumps(entry_payload, ensure_ascii=False) if isinstance(entry_payload, dict) else str(entry_payload)
                haystack = f"{entry_name} {serialized_entry}".casefold()
                if query_text in haystack or any(token in haystack for token in _normalize_query_tokens(query)):
                    description = ""
                    if isinstance(entry_payload, dict):
                        description = str(entry_payload.get("description") or entry_payload.get("summary") or "").strip()
                    matched_entries.append(f"- {entry_name} ({section_name}): {description}".rstrip(": "))
            if len(matched_entries) >= 3:
                break
        if not matched_entries:
            return ""
        return "\n".join(["Relevant Rules Data:", *matched_entries])

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

        query = " ".join(tokens).strip()
        if query:
            for entry in self.campaign_database.search_memory_records(query, limit=2):
                lines.append(f"- Memory match ({entry['memory_type']}): {entry['summary']}")

        if not lines:
            return ""
        return "\n".join(["Relevant Campaign Context:", *lines[:4]])

    def _notebook_context(self, tokens: list[str]) -> str:
        notebook_sources = self.load_notebook_sources()
        matches: list[str] = []
        for name, content in notebook_sources.items():
            lowered = content.casefold()
            if not any(token in lowered or token in name.casefold() for token in tokens):
                continue
            excerpt = self._excerpt_for_tokens(content, tokens)
            matches.append(f"- {name}: {excerpt}")
            if len(matches) >= 2:
                break
        if not matches:
            return ""
        return "\n".join(["Relevant Notebook Sources:", *matches])

    def _all_character_sheets(self) -> list[dict[str, Any]]:
        characters = getattr(self.character_roster, "_characters", {})
        if not isinstance(characters, dict):
            return []
        sheets: list[dict[str, Any]] = []
        for character in characters.values():
            to_dict = getattr(character, "to_dict", None)
            if callable(to_dict):
                sheets.append(to_dict())
        return sheets

    @staticmethod
    def _excerpt_for_tokens(content: str, tokens: list[str]) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            return ""
        lowered = normalized.casefold()
        index = min((lowered.find(token) for token in tokens if lowered.find(token) >= 0), default=-1)
        if index < 0:
            return normalized[:MAX_NOTEBOOK_EXCERPT]
        start = max(0, index - 120)
        end = min(len(normalized), index + 380)
        excerpt = normalized[start:end].strip()
        if start > 0:
            excerpt = "…" + excerpt
        if end < len(normalized):
            excerpt = excerpt + "…"
        return excerpt
