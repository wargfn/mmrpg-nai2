"""Campaign planning and session wrap-up helpers."""

from __future__ import annotations

from typing import Any

from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase, get_campaign_database


class CampaignPlanner:
    """High-level campaign planning facade built on the campaign database."""

    def __init__(self, database: CampaignDatabase | None = None) -> None:
        self.database = database or get_campaign_database()

    def create_campaign_plan(
        self,
        *,
        theme: str,
        villain: str,
        hero_team: list[str] | None = None,
        desired_session_count: int = 3,
    ) -> dict[str, Any]:
        """Create and persist a multi-session campaign plan."""
        cleaned_theme = theme.strip()
        cleaned_villain = villain.strip()
        if not cleaned_theme:
            raise ValueError("Campaign theme is required.")
        if not cleaned_villain:
            raise ValueError("Campaign villain is required.")
        if desired_session_count < 1:
            raise ValueError("Campaign session count must be at least 1.")

        resolved_hero_team = [hero.strip() for hero in (hero_team or ["Marvel heroes"]) if hero.strip()]
        if not resolved_hero_team:
            resolved_hero_team = ["Marvel heroes"]
        sessions = self._build_sessions(
            theme=cleaned_theme,
            villain=cleaned_villain,
            hero_team=resolved_hero_team,
            session_count=desired_session_count,
        )
        campaign_id = self.database.create_campaign_plan(
            theme=cleaned_theme,
            villain=cleaned_villain,
            hero_team=resolved_hero_team,
            sessions=sessions,
        )
        current = self.database.get_campaign_plan(campaign_id)
        if current is None:
            raise RuntimeError("Campaign plan was created but could not be reloaded.")
        if current["campaign_id"] != campaign_id:
            raise RuntimeError("Reloaded campaign plan does not match the created campaign.")
        return current

    def get_current_session_context(self) -> dict[str, Any]:
        """Return the current active session context."""
        context = self.database.get_current_session_context()
        if context is None:
            raise ValueError("No active campaign plan is available.")
        return context

    def conclude_session(self, session_number: int, raw_session_log: str) -> dict[str, Any]:
        """Generate wrap-up artifacts and persist campaign progress."""
        return self.database.conclude_session(session_number=session_number, raw_session_log=raw_session_log)

    @staticmethod
    def _build_sessions(
        *,
        theme: str,
        villain: str,
        hero_team: list[str],
        session_count: int,
    ) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        team_label = ", ".join(hero_team)
        for session_number in range(1, session_count + 1):
            if session_number == 1:
                title = f"{theme} Sparks Fly"
                objectives = [
                    f"Introduce the {theme.lower()} threat facing {team_label}.",
                    f"Reveal the first clue pointing to {villain}.",
                ]
                locations = [f"{theme} hotspot", "New York City"]
                milestone = f"uncover {villain}'s opening move"
            elif session_number == session_count:
                title = f"Final Showdown with {villain}"
                objectives = [
                    f"Confront {villain} at the heart of the {theme.lower()} crisis.",
                    "Resolve the heroes' biggest lingering complication.",
                ]
                locations = [f"{villain}'s stronghold", f"{theme} battleground"]
                milestone = f"stop {villain} and resolve the {theme.lower()} crisis"
            else:
                title = f"{theme} Escalation {session_number}"
                objectives = [
                    f"Pressure one of {villain}'s lieutenants for answers.",
                    f"Escalate the stakes of the {theme.lower()} campaign arc.",
                ]
                locations = [f"{theme} flashpoint {session_number}", f"{villain} safehouse"]
                milestone = f"gain the edge needed for session {session_number + 1}"
            sessions.append(
                {
                    "session_number": session_number,
                    "title": title,
                    "objectives": objectives,
                    "key_npcs": [villain, *hero_team[:2]],
                    "locations": locations,
                    "completion_milestone": milestone,
                }
            )
        return sessions


def create_campaign_plan(
    theme: str,
    villain: str,
    hero_team: list[str] | None = None,
    desired_session_count: int = 3,
) -> dict[str, Any]:
    return CampaignPlanner().create_campaign_plan(
        theme=theme,
        villain=villain,
        hero_team=hero_team,
        desired_session_count=desired_session_count,
    )


def get_current_session_context() -> dict[str, Any]:
    return CampaignPlanner().get_current_session_context()


def conclude_session(session_number: int, raw_session_log: str) -> dict[str, Any]:
    return CampaignPlanner().conclude_session(session_number=session_number, raw_session_log=raw_session_log)
