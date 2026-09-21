"""SQLite-backed persistent campaign memory helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_database_path() -> Path:
    """Return the default persistent campaign database path."""
    return Path(__file__).resolve().parents[3] / "data" / "campaign_memory.db"


CAMPAIGN_DB_PATH = _default_database_path()
SEARCH_RESULT_LIMIT = 10
_ALLOWED_IDENTIFIERS = {
    "npcs": {
        "archetype_or_role",
        "affiliation",
        "disposition",
        "location",
        "notes",
        "custom_stats_json",
    },
    "locations": {"description", "current_status"},
    "plot_logs": {"session_number", "event_summary", "timestamp"},
}


def _quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return f'"{identifier}"'


def _existing_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    if table_name not in _ALLOWED_IDENTIFIERS:
        raise ValueError(f"Unsupported table for migration: {table_name}")
    quoted_table_name = _quote_identifier(table_name)
    return {row[1] for row in connection.execute(f"PRAGMA table_info({quoted_table_name})").fetchall()}


def _ensure_columns(connection: sqlite3.Connection, table_name: str, column_definitions: dict[str, str]) -> None:
    allowed_columns = _ALLOWED_IDENTIFIERS.get(table_name)
    if allowed_columns is None:
        raise ValueError(f"Unsupported table for migration: {table_name}")
    existing_columns = _existing_columns(connection, table_name)
    for column_name, column_definition in column_definitions.items():
        if column_name not in allowed_columns:
            raise ValueError(f"Unsupported column for migration: {table_name}.{column_name}")
        if column_name not in existing_columns:
            normalized_definition = column_definition.upper()
            if "NOT NULL" in normalized_definition and "DEFAULT" not in normalized_definition:
                raise ValueError(
                    f"SQLite migration for {table_name}.{column_name} requires a DEFAULT value for NOT NULL columns."
                )
            quoted_table_name = _quote_identifier(table_name)
            quoted_column_name = _quote_identifier(column_name)
            connection.execute(
                f"ALTER TABLE {quoted_table_name} ADD COLUMN {quoted_column_name} {column_definition}"
            )


def _merge_case_insensitive_npc_duplicates(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT id, name, archetype_or_role, affiliation, disposition, location, notes, custom_stats_json
        FROM npcs
        ORDER BY id
        """
    ).fetchall()
    seen_ids_by_name: dict[str, int] = {}
    for row in rows:
        normalized_name = str(row["name"]).strip().casefold()
        if not normalized_name:
            continue
        primary_id = seen_ids_by_name.get(normalized_name)
        if primary_id is None:
            seen_ids_by_name[normalized_name] = row["id"]
            continue

        primary_row = connection.execute(
            """
            SELECT id, name, archetype_or_role, affiliation, disposition, location, notes, custom_stats_json
            FROM npcs
            WHERE id = ?
            """,
            (primary_id,),
        ).fetchone()
        merged_name = row["name"] or primary_row["name"]
        merged_role = row["archetype_or_role"] or primary_row["archetype_or_role"]
        merged_affiliation = row["affiliation"] or primary_row["affiliation"]
        merged_disposition = row["disposition"] or primary_row["disposition"]
        merged_location = row["location"] or primary_row["location"]
        merged_notes = row["notes"] or primary_row["notes"]
        merged_custom_stats = row["custom_stats_json"] or primary_row["custom_stats_json"]
        connection.execute("DELETE FROM npcs WHERE id = ?", (row["id"],))
        connection.execute(
            """
            UPDATE npcs
            SET
                name = ?,
                archetype_or_role = ?,
                affiliation = ?,
                disposition = ?,
                location = ?,
                notes = ?,
                custom_stats_json = ?
            WHERE id = ?
            """,
            (
                merged_name,
                merged_role,
                merged_affiliation,
                merged_disposition,
                merged_location,
                merged_notes,
                merged_custom_stats,
                primary_row["id"],
            ),
        )


def _rebuild_npcs_table_without_case_sensitive_unique(connection: sqlite3.Connection) -> None:
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'npcs'"
    ).fetchone()
    if table_sql is None or "UNIQUE" not in str(table_sql[0]).upper():
        return

    connection.execute(
        """
        CREATE TABLE npcs_rebuilt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            archetype_or_role TEXT,
            affiliation TEXT,
            disposition TEXT,
            location TEXT,
            notes TEXT,
            custom_stats_json TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO npcs_rebuilt (
            id,
            name,
            archetype_or_role,
            affiliation,
            disposition,
            location,
            notes,
            custom_stats_json
        )
        SELECT
            id,
            name,
            archetype_or_role,
            affiliation,
            disposition,
            location,
            notes,
            custom_stats_json
        FROM npcs
        """
    )
    connection.execute("DROP TABLE npcs")
    connection.execute("ALTER TABLE npcs_rebuilt RENAME TO npcs")


def initialize_database(path: Path | str | None = None) -> Path:
    """Create the campaign memory database and schema if needed."""
    db_path = Path(path) if path is not None else CAMPAIGN_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS npcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                archetype_or_role TEXT,
                affiliation TEXT,
                disposition TEXT,
                location TEXT,
                notes TEXT,
                custom_stats_json TEXT
            )
            """
        )
        _ensure_columns(
            connection,
            "npcs",
            {
                "archetype_or_role": "TEXT",
                "affiliation": "TEXT",
                "disposition": "TEXT",
                "location": "TEXT",
                "notes": "TEXT",
                "custom_stats_json": "TEXT",
            },
        )
        _rebuild_npcs_table_without_case_sensitive_unique(connection)
        _merge_case_insensitive_npc_duplicates(connection)
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_npcs_name_nocase ON npcs (name COLLATE NOCASE)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                current_status TEXT
            )
            """
        )
        _ensure_columns(
            connection,
            "locations",
            {
                "description": "TEXT",
                "current_status": "TEXT",
            },
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
        _ensure_columns(
            connection,
            "plot_logs",
            {
                "session_number": "INTEGER NOT NULL DEFAULT 1",
                "event_summary": "TEXT NOT NULL DEFAULT ''",
                "timestamp": "TEXT NOT NULL DEFAULT ''",
            },
        )
        connection.commit()
    return db_path


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = initialize_database(path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def save_npc(name: str, affiliation: str, description: str, notes: str) -> str:
    """Persist or update an NPC in campaign memory."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("NPC name is required.")

    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_npc = connection.execute(
            "SELECT id FROM npcs WHERE name = ? COLLATE NOCASE",
            (cleaned_name,),
        ).fetchone()
        if existing_npc is None:
            connection.execute(
                """
                INSERT INTO npcs (name, archetype_or_role, affiliation, notes, custom_stats_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cleaned_name,
                    description.strip() or None,
                    affiliation.strip() or None,
                    notes.strip() or None,
                    json.dumps({}),
                ),
            )
        else:
            connection.execute(
                """
                UPDATE npcs
                SET
                    name = ?,
                    archetype_or_role = COALESCE(?, archetype_or_role),
                    affiliation = COALESCE(?, affiliation),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (
                    cleaned_name,
                    description.strip() or None,
                    affiliation.strip() or None,
                    notes.strip() or None,
                    existing_npc["id"],
                ),
            )
        connection.commit()
    return f"Saved NPC '{cleaned_name}'."


def get_npc(name: str) -> dict[str, Any]:
    """Return a persisted NPC by name."""
    cleaned_name = name.strip()
    if not cleaned_name:
        return {}

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                archetype_or_role,
                affiliation,
                disposition,
                location,
                notes,
                custom_stats_json
            FROM npcs
            WHERE name = ? COLLATE NOCASE
            """,
            (cleaned_name,),
        ).fetchone()

    if row is None:
        return {}

    payload = dict(row)
    raw_stats = payload.get("custom_stats_json")
    payload["custom_stats_json"] = json.loads(raw_stats) if raw_stats else {}
    return payload


def log_event(summary: str, session: int = 1) -> str:
    """Append a plot event to the persistent campaign log."""
    cleaned_summary = summary.strip()
    if not cleaned_summary:
        raise ValueError("Event summary is required.")
    if session < 1:
        raise ValueError("Session number must be at least 1.")

    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO plot_logs (session_number, event_summary, timestamp)
            VALUES (?, ?, ?)
            """,
            (session, cleaned_summary, timestamp),
        )
        connection.commit()
    return f"Logged campaign event for session {session}."


def search_memory(query: str) -> list[dict[str, Any]]:
    """Search NPCs, locations, and plot logs for matching campaign memory."""
    keyword = query.strip()
    if not keyword:
        return []

    pattern = f"%{keyword}%"
    with _connect() as connection:
        npc_rows = connection.execute(
            """
            SELECT
                'npc' AS memory_type,
                name,
                affiliation,
                archetype_or_role AS summary,
                notes
            FROM npcs
            WHERE
                name LIKE ? COLLATE NOCASE OR
                affiliation LIKE ? COLLATE NOCASE OR
                archetype_or_role LIKE ? COLLATE NOCASE OR
                notes LIKE ? COLLATE NOCASE
            ORDER BY name
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, SEARCH_RESULT_LIMIT),
        ).fetchall()
        location_rows = connection.execute(
            """
            SELECT
                'location' AS memory_type,
                name,
                current_status AS affiliation,
                description AS summary,
                current_status AS notes
            FROM locations
            WHERE
                name LIKE ? COLLATE NOCASE OR
                description LIKE ? COLLATE NOCASE OR
                current_status LIKE ? COLLATE NOCASE
            ORDER BY name
            LIMIT ?
            """,
            (pattern, pattern, pattern, SEARCH_RESULT_LIMIT),
        ).fetchall()
        plot_rows = connection.execute(
            """
            SELECT
                'plot_log' AS memory_type,
                ('Session ' || session_number) AS name,
                timestamp AS affiliation,
                event_summary AS summary,
                event_summary AS notes
            FROM plot_logs
            WHERE
                event_summary LIKE ? COLLATE NOCASE OR
                timestamp LIKE ? COLLATE NOCASE
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, pattern, SEARCH_RESULT_LIMIT),
        ).fetchall()

    return [dict(row) for row in [*npc_rows, *location_rows, *plot_rows][:SEARCH_RESULT_LIMIT]]
