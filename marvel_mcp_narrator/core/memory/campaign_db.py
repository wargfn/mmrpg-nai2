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


def initialize_database(path: Path | str | None = None) -> Path:
    """Create the campaign memory database and schema if needed."""
    db_path = Path(path) if path is not None else CAMPAIGN_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS npcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
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
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                current_status TEXT
            )
            """
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
        connection.execute(
            """
            INSERT INTO npcs (name, archetype_or_role, affiliation, notes, custom_stats_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                archetype_or_role = excluded.archetype_or_role,
                affiliation = excluded.affiliation,
                notes = excluded.notes,
                custom_stats_json = excluded.custom_stats_json
            """,
            (
                cleaned_name,
                description.strip() or None,
                affiliation.strip() or None,
                notes.strip() or None,
                json.dumps({}),
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
            WHERE lower(name) = lower(?)
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
            """,
            (pattern, pattern, pattern, pattern),
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
            """,
            (pattern, pattern, pattern),
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
            """,
            (pattern, pattern),
        ).fetchall()

    return [dict(row) for row in [*npc_rows, *location_rows, *plot_rows]]
