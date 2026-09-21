"""SQLite-backed persistent campaign memory and entity tracking."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEARCH_RESULT_LIMIT = 10


def _default_database_path() -> Path:
    """Return the default persistent campaign database path."""
    return Path(__file__).resolve().parents[3] / "data" / "campaign.db"


CAMPAIGN_DB_PATH = _default_database_path()
_DEFAULT_DATABASE: CampaignDatabase | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CampaignDatabase:
    """Persistent key-value memory and named entity store for campaign state."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else CAMPAIGN_DB_PATH
        self._initialized = False

    def initialize(self) -> Path:
        """Create the database schema and perform lightweight legacy migrations."""
        if self._initialized and self.path.exists():
            return self.path

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    disposition TEXT NOT NULL DEFAULT 'Neutral',
                    location TEXT NOT NULL DEFAULT 'Unknown',
                    notes TEXT NOT NULL DEFAULT '',
                    affiliation TEXT NOT NULL DEFAULT '',
                    custom_stats_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_category_name ON entities (category, name COLLATE NOCASE)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plot_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_number INTEGER NOT NULL,
                    event_summary TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self._migrate_legacy_tables(connection)
            connection.commit()

        self._initialized = True
        return self.path

    def _connect(self) -> sqlite3.Connection:
        self.initialize()
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate_legacy_tables(self, connection: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "npcs" in tables:
            self._migrate_legacy_npcs(connection)
            if "npcs_legacy_backup" not in tables:
                connection.execute("ALTER TABLE npcs RENAME TO npcs_legacy_backup")
        if "locations" in tables:
            self._migrate_legacy_locations(connection)
            if "locations_legacy_backup" not in tables:
                connection.execute("ALTER TABLE locations RENAME TO locations_legacy_backup")

    def _migrate_legacy_npcs(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT
                name,
                archetype_or_role,
                affiliation,
                disposition,
                location,
                notes,
                custom_stats_json
            FROM npcs
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            name = str(row["name"]).strip()
            if not name:
                continue
            legacy_role = str(row["archetype_or_role"] or "").strip()
            try:
                legacy_stats = json.loads(str(row["custom_stats_json"] or "{}"))
                if not isinstance(legacy_stats, dict):
                    legacy_stats = {}
            except json.JSONDecodeError:
                legacy_stats = {}
            if legacy_role:
                legacy_stats.setdefault("legacy_role", legacy_role)
            existing = connection.execute(
                "SELECT id, custom_stats_json FROM entities WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            payload = (
                name,
                "NPC",
                legacy_role or "Unknown entity",
                str(row["disposition"] or "Neutral"),
                str(row["location"] or "Unknown"),
                str(row["notes"] or ""),
                str(row["affiliation"] or ""),
                json.dumps(legacy_stats),
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO entities (
                        name,
                        category,
                        description,
                        disposition,
                        location,
                        notes,
                        affiliation,
                        custom_stats_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
            else:
                connection.execute(
                    """
                    UPDATE entities
                    SET
                        name = ?,
                        category = 'NPC',
                        description = ?,
                        disposition = ?,
                        location = ?,
                        notes = ?,
                        affiliation = ?,
                        custom_stats_json = ?
                    WHERE id = ?
                    """,
                    (
                        payload[0],
                        payload[2],
                        payload[3],
                        payload[4],
                        payload[5],
                        payload[6],
                        payload[7],
                        existing["id"],
                    ),
                )

    def _migrate_legacy_locations(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT name, description, current_status FROM locations ORDER BY id"
        ).fetchall()
        for row in rows:
            name = str(row["name"]).strip()
            if not name:
                continue
            existing = connection.execute(
                "SELECT id, category FROM entities WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            payload = (
                name,
                "Location",
                str(row["description"] or "Unknown location"),
                "Neutral",
                name,
                str(row["current_status"] or ""),
                "",
                "{}",
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO entities (
                        name,
                        category,
                        description,
                        disposition,
                        location,
                        notes,
                        affiliation,
                        custom_stats_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
            elif str(existing["category"] or "").casefold() == "location":
                connection.execute(
                    """
                    UPDATE entities
                    SET
                        name = ?,
                        category = 'Location',
                        description = ?,
                        location = ?,
                        notes = ?
                    WHERE id = ?
                    """,
                    (
                        payload[0],
                        payload[2],
                        payload[4],
                        payload[5],
                        existing["id"],
                    ),
                )

    def save_memory(self, key: str, content: str) -> None:
        """Save or update a named campaign memory entry."""
        cleaned_key = key.strip()
        cleaned_content = content.strip()
        if not cleaned_key:
            raise ValueError("Memory key is required.")
        if not cleaned_content:
            raise ValueError("Memory content is required.")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (key, content, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (cleaned_key, cleaned_content, _utc_now()),
            )
            connection.commit()

    def load_memory(self, key: str) -> str | None:
        """Load a saved campaign memory by key."""
        cleaned_key = key.strip()
        if not cleaned_key:
            return None

        with self._connect() as connection:
            row = connection.execute(
                "SELECT content FROM memories WHERE key = ?",
                (cleaned_key,),
            ).fetchone()
        return None if row is None else str(row["content"])

    def save_entity(
        self,
        name: str,
        category: str,
        description: str,
        disposition: str = "Neutral",
        location: str = "Unknown",
        notes: str = "",
        *,
        affiliation: str = "",
        custom_stats_json: dict[str, Any] | None = None,
    ) -> None:
        """Save or update an NPC, faction, or location."""
        cleaned_name = name.strip()
        cleaned_category = category.strip()
        cleaned_description = description.strip()
        if not cleaned_name:
            raise ValueError("Entity name is required.")
        if not cleaned_category:
            raise ValueError("Entity category is required.")
        if not cleaned_description:
            raise ValueError("Entity description is required.")

        with self._connect() as connection:
            serialized_stats = json.dumps(custom_stats_json or {})
            connection.execute(
                """
                INSERT INTO entities (
                    name,
                    category,
                    description,
                    disposition,
                    location,
                    notes,
                    affiliation,
                    custom_stats_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category = excluded.category,
                    description = excluded.description,
                    disposition = excluded.disposition,
                    location = excluded.location,
                    notes = excluded.notes,
                    affiliation = excluded.affiliation,
                    custom_stats_json = excluded.custom_stats_json
                """,
                (
                    cleaned_name,
                    cleaned_category,
                    cleaned_description,
                    disposition.strip() or "Neutral",
                    location.strip() or "Unknown",
                    notes.strip(),
                    affiliation.strip(),
                    serialized_stats,
                ),
            )
            connection.commit()

    def get_entity(self, name: str) -> dict[str, Any] | None:
        """Return an entity by name."""
        cleaned_name = name.strip()
        if not cleaned_name:
            return None

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    category,
                    description,
                    disposition,
                    location,
                    notes,
                    affiliation,
                    custom_stats_json
                FROM entities
                WHERE name = ? COLLATE NOCASE
                """,
                (cleaned_name,),
            ).fetchone()
        return self._row_to_entity(row)

    def search_entities(self, query: str) -> list[dict[str, Any]]:
        """Search entities by name and descriptive fields."""
        keyword = query.strip()
        if not keyword:
            return []

        exact_match = self.get_entity(keyword)
        if exact_match is not None:
            return [exact_match]

        pattern = f"%{keyword}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    name,
                    category,
                    description,
                    disposition,
                    location,
                    notes,
                    affiliation,
                    custom_stats_json
                FROM entities
                WHERE
                    name LIKE ? COLLATE NOCASE OR
                    category LIKE ? COLLATE NOCASE OR
                    description LIKE ? COLLATE NOCASE OR
                    disposition LIKE ? COLLATE NOCASE OR
                    location LIKE ? COLLATE NOCASE OR
                    notes LIKE ? COLLATE NOCASE OR
                    affiliation LIKE ? COLLATE NOCASE
                ORDER BY
                    CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END,
                    name COLLATE NOCASE
                LIMIT ?
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    keyword,
                    SEARCH_RESULT_LIMIT,
                ),
            ).fetchall()
        return [self._row_to_entity(row) for row in rows if row is not None]

    def list_memories(self) -> list[dict[str, Any]]:
        """List all saved memories, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, content, updated_at FROM memories ORDER BY updated_at DESC, key ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def search_memory_records(self, query: str, limit: int = SEARCH_RESULT_LIMIT) -> list[dict[str, Any]]:
        """Search saved memories and plot logs for legacy compatibility flows."""
        keyword = query.strip()
        if not keyword:
            return []

        with self._connect() as connection:
            memory_matches = [
                {
                    "memory_type": "memory",
                    "name": row["key"],
                    "affiliation": row["updated_at"],
                    "summary": row["content"],
                    "notes": row["content"],
                }
                for row in connection.execute(
                    """
                    SELECT key, content, updated_at
                    FROM memories
                    WHERE key LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE
                    ORDER BY updated_at DESC, key ASC
                    LIMIT ?
                    """,
                    (f"%{keyword}%", f"%{keyword}%", limit),
                ).fetchall()
            ]
            plot_log_matches = [
                {
                    "memory_type": "plot_log",
                    "name": f"Session {row['session_number']}",
                    "affiliation": row["timestamp"],
                    "summary": row["event_summary"],
                    "notes": row["event_summary"],
                }
                for row in connection.execute(
                    """
                    SELECT session_number, event_summary, timestamp
                    FROM plot_logs
                    WHERE event_summary LIKE ? COLLATE NOCASE
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (f"%{keyword}%", limit),
                ).fetchall()
            ]
        combined_matches = [*memory_matches, *plot_log_matches]
        combined_matches.sort(key=lambda item: str(item.get("affiliation", "")), reverse=True)
        return combined_matches[:limit]

    def add_plot_log(self, summary: str, session: int = 1) -> None:
        """Persist a legacy-style plot log entry."""
        cleaned_summary = summary.strip()
        if not cleaned_summary:
            raise ValueError("Event summary is required.")
        if session < 1:
            raise ValueError("Session number must be at least 1.")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plot_logs (session_number, event_summary, timestamp)
                VALUES (?, ?, ?)
                """,
                (session, cleaned_summary, _utc_now()),
            )
            connection.commit()

    @staticmethod
    def _row_to_entity(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        raw_stats = str(payload.get("custom_stats_json") or "{}")
        try:
            payload["custom_stats_json"] = json.loads(raw_stats)
        except json.JSONDecodeError:
            payload["custom_stats_json"] = {}
        return payload


def get_campaign_database(path: Path | str | None = None) -> CampaignDatabase:
    """Return a reusable database wrapper for the default campaign database."""
    global _DEFAULT_DATABASE
    if path is not None:
        return CampaignDatabase(path)
    if _DEFAULT_DATABASE is None or _DEFAULT_DATABASE.path != CAMPAIGN_DB_PATH:
        _DEFAULT_DATABASE = CampaignDatabase(CAMPAIGN_DB_PATH)
    return _DEFAULT_DATABASE


def initialize_database(path: Path | str | None = None) -> Path:
    """Compatibility wrapper that initializes the campaign database."""
    return get_campaign_database(path).initialize()


def save_memory(key: str, content: str) -> str:
    get_campaign_database().save_memory(key=key, content=content)
    return f"Saved campaign memory '{key.strip()}'."


def load_memory(key: str) -> str | None:
    return get_campaign_database().load_memory(key=key)


def save_entity(
    name: str,
    category: str,
    description: str,
    disposition: str = "Neutral",
    location: str = "Unknown",
    notes: str = "",
    *,
    affiliation: str = "",
    custom_stats_json: dict[str, Any] | None = None,
) -> None:
    get_campaign_database().save_entity(
        name=name,
        category=category,
        description=description,
        disposition=disposition,
        location=location,
        notes=notes,
        affiliation=affiliation,
        custom_stats_json=custom_stats_json,
    )


def get_entity(name: str) -> dict[str, Any] | None:
    return get_campaign_database().get_entity(name)


def search_entities(query: str) -> list[dict[str, Any]]:
    return get_campaign_database().search_entities(query)


def list_memories() -> list[dict[str, Any]]:
    return get_campaign_database().list_memories()


def save_npc(name: str, affiliation: str = "", description: str = "", notes: str = "") -> str:
    """Backward-compatible helper for storing NPC entities."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("NPC name is required.")
    save_entity(
        name=cleaned_name,
        category="NPC",
        description=description or "Unknown NPC",
        notes=notes,
        affiliation=affiliation,
    )
    return f"Saved NPC '{cleaned_name}'."


def get_npc(name: str) -> dict[str, Any] | None:
    """Backward-compatible NPC lookup."""
    entity = get_entity(name)
    if entity is None or str(entity.get("category", "")).casefold() != "npc":
        return None
    entity["archetype_or_role"] = entity.get("custom_stats_json", {}).get("legacy_role") or entity.get("description")
    return entity


def log_event(summary: str, session: int = 1) -> str:
    """Backward-compatible plot log storage using the plot_logs table."""
    get_campaign_database().add_plot_log(summary=summary, session=session)
    return f"Logged campaign event for session {session}."


def search_memory(query: str) -> list[dict[str, Any]]:
    """Backward-compatible memory search across entities and saved memories."""
    keyword = query.strip()
    if not keyword:
        return []

    entity_matches = [
        {
            "memory_type": "entity",
            "name": entity["name"],
            "affiliation": entity.get("category", ""),
            "summary": entity.get("description", ""),
            "notes": entity.get("notes", ""),
            "_priority": 0 if str(entity.get("name", "")).casefold() == keyword.casefold() else 2,
        }
        for entity in search_entities(keyword)
    ]
    legacy_matches = [
        {
            **match,
            "_priority": 1,
        }
        for match in get_campaign_database().search_memory_records(
            keyword,
            limit=SEARCH_RESULT_LIMIT,
        )
    ]
    combined_matches = [*entity_matches, *legacy_matches]
    combined_matches.sort(key=lambda item: item["_priority"])
    ordered_matches = []
    for match in combined_matches:
        cleaned = dict(match)
        cleaned.pop("_priority", None)
        ordered_matches.append(cleaned)
    return ordered_matches[:SEARCH_RESULT_LIMIT]
