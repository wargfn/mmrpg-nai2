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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme TEXT NOT NULL,
                    villain TEXT NOT NULL,
                    hero_team_json TEXT NOT NULL,
                    session_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    session_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    objectives_json TEXT NOT NULL,
                    key_npcs_json TEXT NOT NULL,
                    locations_json TEXT NOT NULL,
                    completion_milestone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    recap TEXT NOT NULL DEFAULT '',
                    narrator_bridge_prompt TEXT NOT NULL DEFAULT '',
                    hero_highlights_json TEXT NOT NULL DEFAULT '{}',
                    raw_session_log TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (campaign_id) REFERENCES campaign_plans(id),
                    UNIQUE (campaign_id, session_number)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
        if "npcs" in tables and "npcs_legacy_backup" not in tables:
            self._migrate_legacy_npcs(connection)
            connection.execute("ALTER TABLE npcs RENAME TO npcs_legacy_backup")
        if "locations" in tables and "locations_legacy_backup" not in tables:
            self._migrate_legacy_locations(connection)
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
                migrated_name = payload[0]
                migrated_description = payload[2]
                migrated_location = payload[4]
                migrated_notes = payload[5]
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
                        migrated_name,
                        migrated_description,
                        migrated_location,
                        migrated_notes,
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
        if custom_stats_json is not None and not isinstance(custom_stats_json, dict):
            raise ValueError("Entity custom_stats_json must be a dictionary.")

        with self._connect() as connection:
            serialized_stats = json.dumps(custom_stats_json or {})
            existing = connection.execute(
                "SELECT id FROM entities WHERE name = ? COLLATE NOCASE",
                (cleaned_name,),
            ).fetchone()
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
            else:
                connection.execute(
                    """
                    UPDATE entities
                    SET
                        name = ?,
                        category = ?,
                        description = ?,
                        disposition = ?,
                        location = ?,
                        notes = ?,
                        affiliation = ?,
                        custom_stats_json = ?
                    WHERE id = ?
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
                        existing["id"],
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
            rows = connection.execute(
                """
                SELECT memory_type, name, affiliation, summary, notes
                FROM (
                    SELECT
                        'memory' AS memory_type,
                        key AS name,
                        updated_at AS affiliation,
                        content AS summary,
                        content AS notes,
                        updated_at AS sort_timestamp
                    FROM memories
                    WHERE key LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE
                    UNION ALL
                    SELECT
                        'plot_log' AS memory_type,
                        ('Session ' || session_number) AS name,
                        timestamp AS affiliation,
                        event_summary AS summary,
                        event_summary AS notes,
                        timestamp AS sort_timestamp
                    FROM plot_logs
                    WHERE event_summary LIKE ? COLLATE NOCASE
                )
                ORDER BY sort_timestamp DESC, name ASC
                LIMIT ?
                """,
                (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def create_campaign_plan(
        self,
        *,
        theme: str,
        villain: str,
        hero_team: list[str],
        sessions: list[dict[str, Any]],
    ) -> int:
        """Persist a structured campaign plan and mark it active."""
        cleaned_theme = theme.strip()
        cleaned_villain = villain.strip()
        if not cleaned_theme:
            raise ValueError("Campaign theme is required.")
        if not cleaned_villain:
            raise ValueError("Campaign villain is required.")
        if not sessions:
            raise ValueError("At least one campaign session is required.")

        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO campaign_plans (theme, villain, hero_team_json, session_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cleaned_theme,
                    cleaned_villain,
                    json.dumps(hero_team),
                    len(sessions),
                    now,
                    now,
                ),
            )
            campaign_id = int(cursor.lastrowid)
            for session in sessions:
                connection.execute(
                    """
                    INSERT INTO campaign_sessions (
                        campaign_id,
                        session_number,
                        title,
                        objectives_json,
                        key_npcs_json,
                        locations_json,
                        completion_milestone
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        int(session["session_number"]),
                        str(session["title"]),
                        json.dumps(session["objectives"]),
                        json.dumps(session["key_npcs"]),
                        json.dumps(session["locations"]),
                        str(session["completion_milestone"]),
                    ),
                )
            self._set_state(connection, "active_campaign_id", str(campaign_id))
            self._set_state(connection, "active_session_number", "1")
            connection.commit()
        return campaign_id

    def get_active_campaign_plan(self) -> dict[str, Any] | None:
        """Return the current active campaign and all of its sessions."""
        with self._connect() as connection:
            active_campaign_id = self._get_state(connection, "active_campaign_id")
            active_session_value = self._get_state(connection, "active_session_number")
            if active_campaign_id is None or active_session_value is None:
                return None
            try:
                campaign_id = int(active_campaign_id)
                active_session_number = int(active_session_value)
            except ValueError:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
            if active_session_number < 1:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
        plan = self.get_campaign_plan(campaign_id)
        if plan is not None and any(
            session["session_number"] == active_session_number
            for session in plan["sessions"]
        ):
            return plan
        with self._connect() as connection:
            self._clear_state(connection, "active_campaign_id")
            self._clear_state(connection, "active_session_number")
            connection.commit()
        return None

    def get_campaign_plan(self, campaign_id: int) -> dict[str, Any] | None:
        """Return a campaign plan and all of its sessions by id."""
        with self._connect() as connection:
            plan_row = connection.execute(
                """
                SELECT id, theme, villain, hero_team_json, session_count, created_at, updated_at
                FROM campaign_plans
                WHERE id = ?
                """,
                (campaign_id,),
            ).fetchone()
            if plan_row is None:
                return None
            session_rows = connection.execute(
                """
                SELECT
                    session_number,
                    title,
                    objectives_json,
                    key_npcs_json,
                    locations_json,
                    completion_milestone,
                    status,
                    recap,
                    narrator_bridge_prompt,
                    hero_highlights_json,
                    raw_session_log
                FROM campaign_sessions
                WHERE campaign_id = ?
                ORDER BY session_number ASC
                """,
                (campaign_id,),
            ).fetchall()
        payload = dict(plan_row)
        payload["campaign_id"] = int(payload["id"])
        payload["hero_team"] = json.loads(payload.pop("hero_team_json"))
        payload["sessions"] = [self._row_to_campaign_session(row) for row in session_rows]
        return payload

    def get_current_session_context(self) -> dict[str, Any] | None:
        """Return the active session roadmap entry for the current campaign."""
        with self._connect() as connection:
            active_campaign_id = self._get_state(connection, "active_campaign_id")
            active_session_value = self._get_state(connection, "active_session_number")
            if active_campaign_id is None or active_session_value is None:
                return None
            try:
                campaign_id = int(active_campaign_id)
                active_session_number = int(active_session_value)
            except ValueError:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
            if active_session_number < 1:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
            plan_row = connection.execute(
                """
                SELECT id, theme, villain, hero_team_json, session_count, created_at, updated_at
                FROM campaign_plans
                WHERE id = ?
                """,
                (campaign_id,),
            ).fetchone()
            if plan_row is None:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
            session_rows = connection.execute(
                """
                SELECT
                    session_number,
                    title,
                    objectives_json,
                    key_npcs_json,
                    locations_json,
                    completion_milestone,
                    status,
                    recap,
                    narrator_bridge_prompt,
                    hero_highlights_json,
                    raw_session_log
                FROM campaign_sessions
                WHERE campaign_id = ?
                ORDER BY session_number ASC
                """,
                (campaign_id,),
            ).fetchall()
            sessions = [self._row_to_campaign_session(row) for row in session_rows]
            current_session = next(
                (session for session in sessions if session["session_number"] == active_session_number),
                None,
            )
            if current_session is None:
                self._clear_state(connection, "active_campaign_id")
                self._clear_state(connection, "active_session_number")
                connection.commit()
                return None
            return {
                "campaign_id": int(plan_row["id"]),
                "theme": str(plan_row["theme"]),
                "villain": str(plan_row["villain"]),
                "hero_team": json.loads(str(plan_row["hero_team_json"])),
                "session_count": int(plan_row["session_count"]),
                "active_session_number": active_session_number,
                "session": current_session,
                "sessions": sessions,
            }

    def conclude_session(self, session_number: int, raw_session_log: str) -> dict[str, Any]:
        """Store recap/highlights for a session, log significant events, and advance progress."""
        cleaned_log = raw_session_log.strip()
        if session_number < 1:
            raise ValueError("Session number must be at least 1.")
        if not cleaned_log:
            raise ValueError("Session log is required.")

        context = self.get_current_session_context()
        if context is None:
            raise ValueError("No active campaign plan is available.")
        if session_number != int(context["active_session_number"]):
            raise ValueError(
                f"Session {session_number} cannot be concluded while session "
                f"{context['active_session_number']} is active."
            )
        session = context["session"]
        if session is None:
            raise ValueError(f"Session {session_number} is not part of the active campaign.")

        player_recap = self._build_player_recap(session, cleaned_log)
        hero_highlights = self._extract_hero_highlights(context["hero_team"], cleaned_log)
        significant_events = self._extract_significant_events(cleaned_log)
        next_session = next(
            (entry for entry in context["sessions"] if entry["session_number"] == session_number + 1),
            None,
        )
        narrator_bridge_prompt = self._build_narrator_bridge_prompt(
            session=session,
            next_session=next_session,
            player_recap=player_recap,
            significant_events=significant_events,
        )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE campaign_sessions
                SET
                    status = 'completed',
                    recap = ?,
                    narrator_bridge_prompt = ?,
                    hero_highlights_json = ?,
                    raw_session_log = ?
                WHERE campaign_id = ? AND session_number = ?
                """,
                (
                    player_recap,
                    narrator_bridge_prompt,
                    json.dumps(hero_highlights),
                    cleaned_log,
                    context["campaign_id"],
                    session_number,
                ),
            )
            for index, event in enumerate(significant_events, start=1):
                self._save_memory_with_connection(
                    connection,
                    key=f"campaign_{context['campaign_id']}_session_{session_number}_event_{index}",
                    content=event,
                )
            if next_session is not None:
                self._set_state(connection, "active_session_number", str(session_number + 1))
            else:
                self._clear_state(connection, "active_session_number")
                self._clear_state(connection, "active_campaign_id")
            connection.commit()

        return {
            "player_recap": player_recap,
            "narrator_bridge_prompt": narrator_bridge_prompt,
            "hero_highlights": hero_highlights,
            "significant_events": significant_events,
        }

    @staticmethod
    def _row_to_entity(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        raw_stats = str(payload.get("custom_stats_json") or "{}")
        try:
            decoded = json.loads(raw_stats)
            payload["custom_stats_json"] = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            payload["custom_stats_json"] = {}
        return payload

    @staticmethod
    def _row_to_campaign_session(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_number": int(row["session_number"]),
            "title": str(row["title"]),
            "objectives": json.loads(str(row["objectives_json"])),
            "key_npcs": json.loads(str(row["key_npcs_json"])),
            "locations": json.loads(str(row["locations_json"])),
            "completion_milestone": str(row["completion_milestone"]),
            "status": str(row["status"]),
            "recap": str(row["recap"]),
            "narrator_bridge_prompt": str(row["narrator_bridge_prompt"]),
            "hero_highlights": json.loads(str(row["hero_highlights_json"])),
            "raw_session_log": str(row["raw_session_log"]),
        }

    def _state_value(self, key: str) -> str | None:
        with self._connect() as connection:
            return self._get_state(connection, key)

    @staticmethod
    def _get_state(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM campaign_state WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    @staticmethod
    def _set_state(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO campaign_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, _utc_now()),
        )

    @staticmethod
    def _clear_state(connection: sqlite3.Connection, key: str) -> None:
        connection.execute("DELETE FROM campaign_state WHERE key = ?", (key,))

    @staticmethod
    def _save_memory_with_connection(connection: sqlite3.Connection, key: str, content: str) -> None:
        connection.execute(
            """
            INSERT INTO memories (key, content, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (key, content, _utc_now()),
        )

    @staticmethod
    def _build_player_recap(session: dict[str, Any], raw_session_log: str) -> str:
        first_sentence = raw_session_log.split(".")[0].strip()
        opening = first_sentence if first_sentence else raw_session_log
        opening_suffix = "" if opening.endswith(("!", "?", ".")) else "."
        return (
            f"Session {session['session_number']} - {session['title']}: {opening}{opening_suffix} "
            f"The heroes advanced toward {session['completion_milestone']}."
        )

    @staticmethod
    def _extract_hero_highlights(hero_team: list[str], raw_session_log: str) -> dict[str, list[str]]:
        highlights: dict[str, list[str]] = {}
        sentences = [part.strip() for part in raw_session_log.replace("\n", " ").split(".") if part.strip()]
        for hero in hero_team:
            hero_key = str(hero).strip()
            if not hero_key:
                continue
            matched = [sentence for sentence in sentences if hero_key.casefold() in sentence.casefold()]
            if matched:
                highlights[hero_key] = matched
        if not highlights:
            highlights["Team"] = sentences[:2] or [raw_session_log.strip()]
        return highlights

    @staticmethod
    def _extract_significant_events(raw_session_log: str) -> list[str]:
        keywords = ("defeat", "resc", "uncover", "discover", "escape", "save", "destroy", "steal", "capture")
        sentences = [part.strip() for part in raw_session_log.replace("\n", " ").split(".") if part.strip()]
        events = [sentence for sentence in sentences if any(keyword in sentence.casefold() for keyword in keywords)]
        return events or sentences[:2]

    @staticmethod
    def _build_narrator_bridge_prompt(
        *,
        session: dict[str, Any],
        next_session: dict[str, Any] | None,
        player_recap: str,
        significant_events: list[str],
    ) -> str:
        if next_session is None:
            return (
                f"Continue from the fallout of session {session['session_number']}. "
                f"Use the recap '{player_recap}' and close lingering threads: {'; '.join(significant_events)}."
            )
        return (
            f"Open session {next_session['session_number']} titled '{next_session['title']}'. "
            f"Carry forward these developments: {'; '.join(significant_events)}. "
            f"Guide the heroes toward {next_session['completion_milestone']}."
        )


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
            "_priority": 1 if str(entity.get("name", "")).casefold() == keyword.casefold() else 2,
        }
        for entity in search_entities(keyword)
    ]
    legacy_matches = [
        {
            **match,
            "_priority": 0,
            "_order": index,
        }
        for index, match in enumerate(get_campaign_database().search_memory_records(
            keyword,
            limit=SEARCH_RESULT_LIMIT,
        ))
    ]
    for index, match in enumerate(entity_matches):
        match["_order"] = index
    combined_matches = [*entity_matches, *legacy_matches]
    combined_matches.sort(key=lambda item: (item["_priority"], item["_order"]))
    ordered_matches = []
    for match in combined_matches:
        cleaned = dict(match)
        cleaned.pop("_priority", None)
        cleaned.pop("_order", None)
        ordered_matches.append(cleaned)
    return ordered_matches[:SEARCH_RESULT_LIMIT]
