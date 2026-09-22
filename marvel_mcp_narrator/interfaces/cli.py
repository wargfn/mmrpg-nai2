"""Interactive Open WebUI-backed CLI loop for local narrator/copilot experiments."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tomllib
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from marvel_mcp_narrator.core.character_creation import ABILITY_FIELDS
from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError, roll_d616
from marvel_mcp_narrator.core.memory.campaign_db import (
    CampaignDatabase,
    get_campaign_database,
)
from marvel_mcp_narrator.core.rules_database import RulesLookupError, load_rules_database
from marvel_mcp_narrator.core.session_controller import GameSessionController

_ACTIVE_SESSION_CONTROLLER: ContextVar[Any | None] = ContextVar("cli_session_controller", default=None)
_DEFAULT_SESSION_CONTROLLER: GameSessionController | None = None


def _get_session_controller() -> GameSessionController:
    controller = _ACTIVE_SESSION_CONTROLLER.get()
    if controller is not None:
        return controller
    global _DEFAULT_SESSION_CONTROLLER
    if _DEFAULT_SESSION_CONTROLLER is None:
        _DEFAULT_SESSION_CONTROLLER = GameSessionController()
    return _DEFAULT_SESSION_CONTROLLER


def resolve_d616_roll(
    ability_modifier: int = 0,
    target_number: int | None = None,
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    return _get_session_controller().roll_action(
        ability_modifier=ability_modifier,
        target_number=target_number,
        edges=edges,
        troubles=troubles,
    )


def query_rulebook_database(query: str) -> str:
    return _get_session_controller().look_up_rule(query)


def clear_combat_state() -> None:
    _get_session_controller().clear_combat_state()


def get_combat_state() -> dict[str, Any]:
    return _get_session_controller().get_combat_state()


def list_campaign_memories(limit: int | None = None) -> list[dict[str, Any]]:
    return _get_session_controller().list_campaign_memories(limit=limit)


def resolve_manual_d616_roll(
    *,
    dice_values: list[int],
    marvel_index: int = 1,
    ability_modifier: int = 0,
    target_number: int | None = None,
) -> dict[str, Any]:
    return _get_session_controller().resolve_manual_roll(
        dice_values=dice_values,
        marvel_index=marvel_index,
        ability_modifier=ability_modifier,
        target_number=target_number,
    )


def resolve_player_attack(
    *,
    attacker_name: str,
    target_name: str,
    ability: str,
    dice_values: list[int] | None = None,
    marvel_index: int = 1,
    target_resource: str = "health",
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    return _get_session_controller().resolve_player_attack(
        attacker_name=attacker_name,
        target_name=target_name,
        ability=ability,
        dice_values=dice_values,
        marvel_index=marvel_index,
        target_resource=target_resource,
        edges=edges,
        troubles=troubles,
    )


def resolve_npc_action(
    *,
    attacker_name: str,
    target_name: str,
    ability: str,
    target_resource: str = "health",
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    return _get_session_controller().resolve_npc_action(
        attacker_name=attacker_name,
        target_name=target_name,
        ability=ability,
        target_resource=target_resource,
        edges=edges,
        troubles=troubles,
    )

SYSTEM_PROMPT = (
    "You are a Marvel Multiverse RPG narrator copilot. "
    "Use deterministic tool outputs provided in context for dice and rules."
)
DEFAULT_MODEL = "qwen2.5:14b-instruct"
DEFAULT_OPEN_WEBUI_HOST = "http://127.0.0.1:3000"
STARTUP_MEMORY_LIMIT = 12
STARTUP_CONTEXT_CHAR_BUDGET = 6000
RULES_CONTEXT_KEYS = (
    "core_attribute_melee",
    "core_attribute_agility",
    "core_attribute_resilience",
    "core_attribute_vigilance",
    "core_attribute_ego",
    "core_attribute_logic",
    "secondary_defenses",
    "action_check_format",
    "damage_formula",
    "special_rolls",
    "running_speed",
)
CLI_COMMANDS_HELP = "\n".join(
    [
        "Interactive commands:",
        "  /roll [edges] [troubles] or /roll [--edges N] [--troubles N] [--tn N]",
        "                                   Run a deterministic d616 roll",
        "  /attack <attacker> <ability> <target> [manual d616 roll] [--edges N] [--troubles N] [--focus]",
        "                                   Auto-roll or apply a manual player attack",
        "  /npc-attack <attacker> <ability> <target> [--edges N] [--troubles N] [--focus]",
        "                                   Auto-resolve an NPC or enemy action",
        "  /combat                           Show tracked combatant health/focus state",
        "  /rules <keyword>                  Search the local Marvel rulebook",
        "  /memories                         Show stored campaign memories",
        "  /help                              Show command help during a session",
        "  exit | quit | /exit | /quit       Gracefully close the narrator CLI",
        "",
        "You can also press Ctrl+C or Ctrl+D to shut down the CLI safely.",
    ]
)
STARTUP_CONTEXT_EMPTY_NOTE = (
    "No prior campaign memories were found in SQLite campaign memory. "
    "Treat this as a fresh campaign start until new session details are established."
)
STARTUP_CONTEXT_UNAVAILABLE_NOTE = (
    "SQLite campaign memory could not be loaded at startup. "
    "Continue narrating with the live session context only."
)
MANUAL_D616_ROLL_PATTERN = re.compile(r"\[(?P<body>[^\]]+)\]")
MANUAL_D616_ENTRY_PATTERN = re.compile(r"^(?P<value>[1-6])(?:\s*\(\s*marvel\s*\)|\s+marvel)?$", re.IGNORECASE)


def normalize_open_webui_host(host: str) -> str:
    """Normalize a host URL to an Open WebUI base URL."""
    parsed = urlparse(host)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/chat/completions"):
        path = path[: -len("/api/chat/completions")]
    if not path:
        path = ""
    normalized = parsed._replace(path=path)
    return urlunparse(normalized)


def build_open_webui_chat_endpoint(host: str) -> str:
    """Build a chat-completions endpoint URL from OpenWebUI/OpenAI-compatible base URL."""
    normalized_host = normalize_open_webui_host(host)
    parsed = urlparse(normalized_host)
    path = parsed.path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    last_segment = segments[-1] if segments else ""
    is_version_segment = len(last_segment) > 1 and last_segment.startswith("v") and last_segment[1:].isdigit()

    if len(segments) >= 2 and segments[-2:] == ["chat", "completions"]:
        endpoint_segments = segments
    elif segments and segments[-1] == "completions":
        endpoint_segments = segments[:-1] + ["chat", "completions"]
    elif segments and segments[-1] == "chat":
        endpoint_segments = segments + ["completions"]
    elif is_version_segment or (segments and segments[-1] in {"api", "openai"}):
        endpoint_segments = segments + ["chat", "completions"]
    else:
        endpoint_segments = segments + ["api", "chat", "completions"]

    endpoint_path = "/" + "/".join(endpoint_segments)
    return urlunparse(parsed._replace(path=endpoint_path, fragment=""))


def request_open_webui_chat(
    *,
    host: str | None = None,
    base_url: str | None = None,
    model: str,
    messages: list[dict[str, str]],
    api_key: str | None = None,
) -> str:
    """Send a chat request to Open WebUI and return assistant content."""
    endpoint = build_open_webui_chat_endpoint(base_url or host or DEFAULT_OPEN_WEBUI_HOST)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    response = httpx.post(
        endpoint,
        headers=headers,
        json={"model": model, "messages": messages, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
    raise ValueError("No assistant content returned from Open WebUI.")


def load_cli_config(config_path: str | None = None) -> dict[str, str | None]:
    """Load CLI config from file and environment variables."""
    config: dict[str, str | None] = {
        "model": DEFAULT_MODEL,
        "host": DEFAULT_OPEN_WEBUI_HOST,
        "base_url": None,
        "api_key": None,
    }
    has_explicit_base_url = False

    path: Path | None = None
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise ValueError(f"Configuration file not found: {path}")
    else:
        candidate = Path.cwd() / "narrator_config.toml"
        if candidate.exists():
            path = candidate

    if path is not None:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        open_webui_block = data.get("open_webui")
        if not isinstance(open_webui_block, dict):
            open_webui_block = data.get("ollama", {})
        if isinstance(open_webui_block, dict):
            model = open_webui_block.get("model")
            host = open_webui_block.get("host")
            base_url = open_webui_block.get("base_url")
            api_key = open_webui_block.get("api_key")
            if model:
                config["model"] = str(model)
            if base_url:
                config["base_url"] = str(base_url)
                has_explicit_base_url = True
            if host:
                config["host"] = str(host)
                if not base_url:
                    config["base_url"] = str(host)
            if api_key:
                config["api_key"] = str(api_key)

    model_override = os.getenv("NARRATOR_MODEL")
    base_url_override = os.getenv("NARRATOR_BASE_URL") or os.getenv("NARRATOR_OPENAI_BASE_URL")
    host_override = os.getenv("NARRATOR_OPEN_WEBUI_HOST") or os.getenv("NARRATOR_OLLAMA_HOST")
    api_key_override = os.getenv("NARRATOR_API_KEY")
    if model_override:
        config["model"] = model_override
    if base_url_override:
        config["base_url"] = base_url_override
        has_explicit_base_url = True
    if host_override:
        config["host"] = host_override
        if not has_explicit_base_url:
            config["base_url"] = host_override
    if api_key_override:
        config["api_key"] = api_key_override
    return config


def get_startup_context(database: CampaignDatabase | None = None) -> str:
    """Return a structured startup context block from persisted campaign memories."""
    def _truncate_context(context: str) -> str:
        if STARTUP_CONTEXT_CHAR_BUDGET <= 0:
            return ""
        if len(context) <= STARTUP_CONTEXT_CHAR_BUDGET:
            return context
        if STARTUP_CONTEXT_CHAR_BUDGET == 1:
            return "…"
        return context[: STARTUP_CONTEXT_CHAR_BUDGET - 1].rstrip() + "…"

    db = database or get_campaign_database()
    try:
        memories = db.list_memories()
    except (OSError, sqlite3.Error, ValueError):
        return _truncate_context("Campaign Memory Context:\n- " + STARTUP_CONTEXT_UNAVAILABLE_NOTE)

    if not memories:
        return _truncate_context("Campaign Memory Context:\n- " + STARTUP_CONTEXT_EMPTY_NOTE)

    lines = ["Campaign Memory Context:"]
    current_length = len(lines[0])
    total_memories = len(memories)
    rendered_count = 0
    for memory in memories[:STARTUP_MEMORY_LIMIT]:
        key = str(memory.get("key", "")).strip() or "memory"
        content = str(memory.get("content", "")).strip()
        updated_at = str(memory.get("updated_at", "")).strip()
        entry = f"- [{updated_at}] {key}: {content}" if updated_at else f"- {key}: {content}"
        remaining_after_entry = total_memories - (rendered_count + 1)
        omission_line = ""
        if remaining_after_entry > 0:
            omission_line = (
                f"- Additional memories omitted to keep startup context concise "
                f"({remaining_after_entry} more)."
            )
        projected_length = current_length + 1 + len(entry)
        if omission_line:
            projected_length += 1 + len(omission_line)
        if projected_length > STARTUP_CONTEXT_CHAR_BUDGET:
            break
        lines.append(entry)
        current_length += 1 + len(entry)
        rendered_count += 1
    omitted_count = total_memories - rendered_count
    if omitted_count:
        omission_line = f"- Additional memories omitted to keep startup context concise ({omitted_count} more)."
        if current_length + 1 + len(omission_line) <= STARTUP_CONTEXT_CHAR_BUDGET:
            lines.append(omission_line)
        else:
            shorter_line = f"- {omitted_count} more memories omitted."
            if current_length + 1 + len(shorter_line) <= STARTUP_CONTEXT_CHAR_BUDGET:
                lines.append(shorter_line)
            else:
                minimal_line = f"- +{omitted_count}"
                if current_length + 1 + len(minimal_line) <= STARTUP_CONTEXT_CHAR_BUDGET:
                    lines.append(minimal_line)
    if len(lines) == 1:
        fallback = f"Campaign Memory Context:\n- +{max(1, omitted_count or total_memories)}"
        return _truncate_context(fallback)
    return _truncate_context("\n".join(lines))


def get_rules_startup_context() -> str:
    """Return a concise core-rules block for startup prompt injection."""
    try:
        mechanics = load_rules_database().get("mechanics", {})
    except (OSError, ValueError, TypeError, ModuleNotFoundError):
        return "Core d616 Rules Context:\n- Rules database could not be loaded; use deterministic tool outputs for rules lookups."

    lines = ["Core d616 Rules Context:"]
    for key in RULES_CONTEXT_KEYS:
        payload = mechanics.get(key)
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title", key)).strip()
        description = str(payload.get("description", "")).strip()
        formula = str(payload.get("formula", "")).strip()
        examples = payload.get("examples", [])
        line = f"- {title}: {description}"
        if formula:
            line += f" Formula: {formula}."
        if isinstance(examples, list) and examples:
            line += f" Examples: {'; '.join(str(item).strip() for item in examples if str(item).strip())}."
        lines.append(line)
    if len(lines) == 1:
        lines.append("- Core mechanics were not found in the rules database.")
    return "\n".join(lines)


def get_active_character_context() -> str:
    """Return derived-stat context for the currently active tracked character."""
    active_sheet = character_roster.get_active_sheet()
    if active_sheet is None:
        return "Active Character Context:\n- No active character is currently loaded."

    attributes = {
        "Melee": int(active_sheet["melee"]),
        "Agility": int(active_sheet["agility"]),
        "Resilience": int(active_sheet["resilience"]),
        "Vigilance": int(active_sheet["vigilance"]),
        "Ego": int(active_sheet["ego"]),
        "Logic": int(active_sheet["logic"]),
    }
    rank = int(active_sheet["rank"])
    health = attributes["Resilience"] * 25
    focus = attributes["Vigilance"] * 25
    running_speed = 5 + (attributes["Agility"] // 5)
    defenses = {
        "Melee": 10 + attributes["Melee"],
        "Agility": 10 + attributes["Agility"],
        "Resilience": 10 + attributes["Resilience"],
        "Vigilance": 10 + attributes["Vigilance"],
        "Ego": 10 + attributes["Ego"],
        "Logic": 10 + attributes["Logic"],
    }
    return "\n".join(
        [
            "Active Character Context:",
            f"- Name: {active_sheet['name']} ({active_sheet['archetype']}, Rank {rank})",
            (
                "- Attributes: "
                + ", ".join(f"{name} {value}" for name, value in attributes.items())
            ),
            (
                "- Derived Stats: "
                f"Health {health}, Focus {focus}, Initiative Modifier +{attributes['Vigilance']}, "
                f"Running Speed {running_speed} spaces"
            ),
            (
                "- Defenses: "
                + ", ".join(f"{name} Defense {value}" for name, value in defenses.items())
            ),
            (
                f"- Damage Math: Base damage = Rank {rank} × Marvel Die; "
                f"current damage multiplier = {rank}"
            ),
        ]
    )


def build_startup_system_prompt(
    database: CampaignDatabase | None = None,
    *,
    rules_context: str | None = None,
    campaign_memory_context: str | None = None,
) -> str:
    """Build the initial system prompt with injected persistent campaign memory."""
    resolved_rules_context = rules_context if rules_context is not None else get_rules_startup_context()
    resolved_memory_context = (
        campaign_memory_context if campaign_memory_context is not None else get_startup_context(database)
    )
    return "\n\n".join(
        [
            SYSTEM_PROMPT,
            resolved_rules_context,
            get_active_character_context(),
            get_active_combat_context(),
            resolved_memory_context,
        ]
    )


def _format_router_roll_result(result: dict[str, Any]) -> str:
    lines = [
        "Deterministic d616 Roll:",
        f"- Dice: {result.get('dice_values', [])}",
        f"- Total Score: {result.get('total_score')}",
        f"- Fantastic: {result.get('is_fantastic')}",
        f"- Ultimate Success: {result.get('is_ultimate')}",
        f"- Botch: {result.get('is_botch')}",
    ]
    target_number = result.get("target_number")
    if target_number is not None:
        lines.append(f"- Target Number: {target_number}")
        lines.append(f"- Success: {result.get('success')}")
    return "\n".join(lines)


def _format_manual_report_result(result: dict[str, Any]) -> str:
    lines = [
        "Manual d616 Report:",
        f"- Reported Dice: {result.get('dice_values', [])}",
        f"- Normalized Dice: {result.get('normalized_dice_values', result.get('dice_values', []))}",
        f"- Total Score (no ability modifier): {result.get('total_score')}",
        f"- Fantastic: {result.get('is_fantastic')}",
        f"- Ultimate Success: {result.get('is_ultimate')}",
        f"- Botch: {result.get('is_botch')}",
        "- Note: This stores the reported roll in chat history without resolving a target number.",
    ]
    return "\n".join(lines)


def _format_router_memories_result(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "Campaign Memories:\n- No stored campaign memories were found."
    lines = ["Campaign Memories:"]
    for memory in memories:
        key = str(memory.get("key", "")).strip() or "memory"
        content = str(memory.get("content", "")).strip()
        updated_at = str(memory.get("updated_at", "")).strip()
        entry = f"- [{updated_at}] {key}: {content}" if updated_at else f"- {key}: {content}"
        lines.append(entry)
    return "\n".join(lines)


def _format_combat_state_result(combat_state: dict[str, Any]) -> str:
    combatants = combat_state.get("combatants", [])
    if not combatants:
        return "Active Combat State:\n- No combatants are currently tracked."
    lines = ["Active Combat State:"]
    for combatant in combatants:
        lines.append(
            f"- [{combatant['side']}] {combatant['name']}: "
            f"Health {combatant['current_health']}/{combatant['max_health']}, "
            f"Focus {combatant['current_focus']}/{combatant['max_focus']}"
        )
    return "\n".join(lines)


def get_active_combat_context() -> str:
    """Return tracked combatant health/focus context for the current session."""
    return _format_combat_state_result(get_combat_state())


def _format_attack_result(payload: dict[str, Any]) -> str:
    roll = payload["roll"]
    lines = [
        f"Combat Resolution: {payload['attacker']['name']} used {payload['ability']} against {payload['target']['name']}",
        f"- Target Number: {payload['target_number']}",
        f"- Dice: {roll.get('dice_values', [])}",
        f"- Total Score: {roll.get('total_score')}",
        f"- Fantastic: {roll.get('is_fantastic')}",
        f"- Success: {roll.get('success')}",
    ]
    if payload.get("damage") is not None:
        lines.append(f"- Damage: {payload['damage']['total_damage']} {payload['target_resource']}")
        lines.append(
            f"- Target Status: {payload['target']['name']} now has "
            f"{payload['target']['current_health']}/{payload['target']['max_health']} Health and "
            f"{payload['target']['current_focus']}/{payload['target']['max_focus']} Focus"
        )
    else:
        lines.append("- Damage: none")
    return "\n".join(lines)


def _parse_manual_roll_text(text: str) -> tuple[list[int], int] | None:
    match = MANUAL_D616_ROLL_PATTERN.search(text)
    if match is None:
        return None
    body = match.group("body")
    entries = [entry.strip() for entry in body.split(",") if entry.strip()]
    if len(entries) != 3:
        raise ValueError("Manual d616 rolls must use three comma-separated dice values.")
    dice_values: list[int] = []
    marvel_index: int | None = None
    for index, entry in enumerate(entries):
        entry_match = MANUAL_D616_ENTRY_PATTERN.fullmatch(entry)
        if entry_match is None:
            raise ValueError(
                "Each manual d616 die entry must be a die value from 1-6 with an optional Marvel marker."
            )
        marvel_marked = "marvel" in entry.casefold()
        value = int(entry_match.group("value"))
        dice_values.append(value)
        if marvel_marked:
            if marvel_index is not None:
                raise ValueError("Manual d616 rolls may only mark one die as the Marvel die.")
            marvel_index = index
    if marvel_index is None:
        raise ValueError("Manual d616 rolls must explicitly mark which die is the Marvel die.")
    return dice_values, marvel_index


def _extract_manual_roll(text: str) -> tuple[tuple[list[int], int] | None, str]:
    match = MANUAL_D616_ROLL_PATTERN.search(text)
    if match is None:
        return None, text
    manual_roll = _parse_manual_roll_text(match.group(0))
    remainder = f"{text[:match.start()]} {text[match.end():]}".strip()
    return manual_roll, remainder


def _parse_roll_command(parts: list[str]) -> tuple[int, int, int | None]:
    edges = 0
    troubles = 0
    tn = None
    seen_edge = False
    seen_trouble = False
    seen_edges = False
    seen_troubles = False
    seen_tn = False
    index = 1
    while index < len(parts):
        token = parts[index]
        if token == "--edge":
            if seen_edge or seen_edges:
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            seen_edge = True
            edges = 1
            index += 1
            continue
        if token == "--trouble":
            if seen_trouble or seen_troubles:
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            seen_trouble = True
            troubles = 1
            index += 1
            continue
        if token == "--edges":
            if seen_edge or seen_edges:
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            seen_edges = True
            if index + 1 >= len(parts):
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            try:
                edges = int(parts[index + 1])
            except ValueError as exc:
                raise ValueError("Edges must be a non-negative integer.") from exc
            if edges < 0:
                raise ValueError("Edges must be a non-negative integer.")
            index += 2
            continue
        if token == "--troubles":
            if seen_trouble or seen_troubles:
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            seen_troubles = True
            if index + 1 >= len(parts):
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            try:
                troubles = int(parts[index + 1])
            except ValueError as exc:
                raise ValueError("Troubles must be a non-negative integer.") from exc
            if troubles < 0:
                raise ValueError("Troubles must be a non-negative integer.")
            index += 2
            continue
        if token == "--tn":
            if seen_tn:
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            seen_tn = True
            if index + 1 >= len(parts):
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            tn_value = parts[index + 1]
            if tn_value.startswith("--"):
                raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
            try:
                tn = int(tn_value)
            except ValueError as exc:
                raise ValueError("Target number for --tn must be a positive integer.") from exc
            if tn <= 0:
                raise ValueError("Target number for --tn must be a positive integer.")
            index += 2
            continue
        raise ValueError("Usage: /roll [--edge|--trouble|--edges N|--troubles N] [--tn N]")
    return edges, troubles, tn


def _parse_attack_command(
    stripped: str, *, command_name: str
) -> tuple[str, str, str, tuple[list[int], int] | None, dict[str, int | str]]:
    remainder = stripped[len(command_name) :].strip()
    if not remainder:
        raise ValueError(f"Usage: {command_name} <attacker> <ability> <target> [manual d616 roll]")
    manual_roll, remainder = _extract_manual_roll(remainder)
    options: dict[str, int | str] = {"edges": 0, "troubles": 0, "target_resource": "health"}
    tokens = remainder.split()
    positional_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--focus":
            options["target_resource"] = "focus"
            index += 1
            continue
        if token == "--health":
            options["target_resource"] = "health"
            index += 1
            continue
        if token in {"--edges", "--troubles"}:
            if index + 1 >= len(tokens):
                raise ValueError(f"Usage: {command_name} <attacker> <ability> <target> [manual d616 roll]")
            try:
                value = int(tokens[index + 1])
            except ValueError as exc:
                raise ValueError("Edges and troubles must be non-negative integers.") from exc
            if value < 0:
                raise ValueError("Edges and troubles must be non-negative integers.")
            options["edges" if token == "--edges" else "troubles"] = value
            index += 2
            continue
        positional_tokens.append(token)
        index += 1
    remainder = " ".join(positional_tokens).strip()
    if "|" in remainder:
        fields = [segment.strip() for segment in remainder.split("|")]
        if len(fields) != 3 or not all(fields):
            raise ValueError(f"Usage: {command_name} <attacker> | <ability> | <target> [| manual d616 roll]")
        attacker_name, ability, target_name = fields
    else:
        parts = remainder.split()
        ability_index = next((index for index, token in enumerate(parts) if token.casefold() in ABILITY_FIELDS), None)
        if ability_index is None:
            raise ValueError(f"Usage: {command_name} <attacker> <ability> <target> [manual d616 roll]")
        attacker_name = " ".join(parts[:ability_index]).strip()
        ability = parts[ability_index]
        target_name = " ".join(parts[ability_index + 1 :]).strip()
        if not attacker_name or not target_name:
            raise ValueError(f"Usage: {command_name} <attacker> <ability> <target> [manual d616 roll]")
    return attacker_name.strip(), ability.strip(), target_name.strip(), manual_roll, options


def _route_intent_command(user_input: str) -> tuple[str, str] | None:
    """Route deterministic CLI commands without invoking the chat model."""
    stripped = user_input.strip()
    if not stripped:
        return None

    standalone_manual_match = re.fullmatch(r"\s*\[[^\]]+\]\s*", user_input)
    if standalone_manual_match is not None:
        manual_roll = _parse_manual_roll_text(standalone_manual_match.group(0))
        if manual_roll is None:
            return None
        dice_values, marvel_index = manual_roll
        return "manual_d616_report", _format_manual_report_result(
            resolve_manual_d616_roll(dice_values=dice_values, marvel_index=marvel_index)
        )

    parts = stripped.split()
    command = parts[0].lower()
    arguments = parts[1:]

    if command in {"/rules", "/rule"}:
        query = " ".join(arguments).strip()
        if not query:
            raise ValueError("Usage: /rules <keyword>")
        return "lookup_rule", query_rulebook_database(query)

    if command == "/memories":
        if arguments:
            raise ValueError("Usage: /memories")
        return "list_memories", _format_router_memories_result(list_campaign_memories())

    if command == "/combat":
        if arguments:
            raise ValueError("Usage: /combat")
        return "combat_state", _format_combat_state_result(get_combat_state())

    if command == "/attack":
        attacker_name, ability, target_name, manual_roll, options = _parse_attack_command(
            stripped, command_name="/attack"
        )
        payload = resolve_player_attack(
            attacker_name=attacker_name,
            target_name=target_name,
            ability=ability,
            dice_values=manual_roll[0] if manual_roll is not None else None,
            marvel_index=manual_roll[1] if manual_roll is not None else 1,
            target_resource=str(options["target_resource"]),
            edges=int(options["edges"]),
            troubles=int(options["troubles"]),
        )
        return "resolve_player_attack", _format_attack_result(payload)

    if command == "/npc-attack":
        attacker_name, ability, target_name, manual_roll, options = _parse_attack_command(
            stripped, command_name="/npc-attack"
        )
        if manual_roll is not None:
            raise ValueError("NPC attacks are always automated; omit manual dice values.")
        return "resolve_npc_action", _format_attack_result(
            resolve_npc_action(
                attacker_name=attacker_name,
                target_name=target_name,
                ability=ability,
                target_resource=str(options["target_resource"]),
                edges=int(options["edges"]),
                troubles=int(options["troubles"]),
            )
        )

    if command == "/roll":
        if any(token.startswith("--") for token in arguments):
            edges, troubles, target_number = _parse_roll_command(parts)
            return "resolve_d616_roll", _format_router_roll_result(
                resolve_d616_roll(edges=edges, troubles=troubles, target_number=target_number)
            )

        if len(arguments) > 2:
            raise ValueError("Usage: /roll [edges] [troubles]")
        try:
            edges = int(arguments[0]) if len(arguments) >= 1 else 0
            troubles = int(arguments[1]) if len(arguments) >= 2 else 0
        except ValueError as exc:
            raise ValueError("Usage: /roll [edges] [troubles]") from exc
        if edges < 0 or troubles < 0:
            raise ValueError("Edges and troubles must be non-negative integers.")
        return "resolve_d616_roll", _format_router_roll_result(
            resolve_d616_roll(edges=edges, troubles=troubles)
        )

    return None


def _tool_injection(user_input: str) -> tuple[str | None, dict[str, Any] | str | None]:
    """Parse slash commands and return (tool_name, tool_output)."""
    stripped = user_input.strip()
    parts = stripped.split()
    if not parts:
        return None, None

    command = parts[0]

    if command == "/roll":
        edges, troubles, tn = _parse_roll_command(parts)
        if "--edges" in parts or "--troubles" in parts or edges > 1 or troubles > 1:
            return "resolve_d616_roll", resolve_d616_roll(edges=edges, troubles=troubles, target_number=tn)
        return "roll_d616", roll_d616(edge=bool(edges), trouble=bool(troubles), target_number=tn)

    if command == "/rule":
        key = " ".join(parts[1:]).strip()
        if not key:
            raise ValueError("Usage: /rule <keyword>")
        return "lookup_rule", query_rulebook_database(key)

    return None, None


def _is_exit_command(user_input: str) -> bool:
    """Return True when the user wants to shut down the CLI."""
    return user_input.strip().lower() in {"exit", "quit", "/exit", "/quit"}


def run_cli(
    model: str,
    host: str = DEFAULT_OPEN_WEBUI_HOST,
    base_url: str | None = None,
    api_key: str | None = None,
    database: CampaignDatabase | None = None,
) -> None:
    """Start an interactive Open WebUI-backed narrator loop."""
    session_controller = GameSessionController(
        campaign_database=database if database is not None else get_campaign_database()
    )
    session_database = session_controller.campaign_database
    controller_token = _ACTIVE_SESSION_CONTROLLER.set(session_controller)
    try:
        clear_combat_state()
        print("Marvel MCP Narrator CLI")
        print("Type '/help' for commands and 'exit' to quit.\n")

        rules_context = get_rules_startup_context()
        campaign_memory_context = get_startup_context(session_database)
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": build_startup_system_prompt(
                    session_database,
                    rules_context=rules_context,
                    campaign_memory_context=campaign_memory_context,
                ),
            }
        ]
        prompt_context_dirty = False

        while True:
            try:
                user_input = input("you> ").strip()
            except EOFError:
                print("Goodbye.")
                return
            except KeyboardInterrupt:
                print("\nGoodbye.")
                return
            if not user_input:
                continue
            if user_input.lower() == "/help":
                print(CLI_COMMANDS_HELP)
                continue
            if _is_exit_command(user_input):
                print("Goodbye.")
                return

            turn_start_index = len(messages)
            try:
                routed = _route_intent_command(user_input)
                if routed is not None:
                    tool_name, formatted_output = routed
                    print(f"{tool_name}> {formatted_output}")
                    messages.append({"role": "user", "content": user_input})
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"Deterministic router output ({tool_name}): {formatted_output}",
                        }
                    )
                    prompt_context_dirty = True
                    continue
                tool_name, tool_output = _tool_injection(user_input)
                if tool_name and tool_output is not None:
                    payload = tool_output if isinstance(tool_output, str) else json.dumps(tool_output, ensure_ascii=False)
                    print(f"tool[{tool_name}]> {payload}")
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"Tool output ({tool_name}): {payload}",
                        }
                    )
                    prompt_context_dirty = True
                else:
                    messages.append({"role": "user", "content": user_input})
            except (ValueError, D616ConfigurationError, RulesLookupError, OSError) as exc:
                print(f"tool_error> {exc}")
                continue

            try:
                if prompt_context_dirty:
                    campaign_memory_context = get_startup_context(session_database)
                    messages[0]["content"] = build_startup_system_prompt(
                        session_database,
                        rules_context=rules_context,
                        campaign_memory_context=campaign_memory_context,
                    )
                    prompt_context_dirty = False
                final_content = request_open_webui_chat(
                    host=host,
                    base_url=base_url or host,
                    model=model,
                    messages=list(messages),
                    api_key=api_key,
                )
                print(f"assistant> {final_content}")
                if final_content:
                    messages.append({"role": "assistant", "content": final_content})
            except (httpx.HTTPError, ValueError, TypeError, Exception) as exc:
                del messages[turn_start_index:]
                message = str(exc)
                if "connection refused" in message.lower():
                    print("chat_error> Connection refused. Is Open WebUI running?")
                elif "405" in message:
                    print("chat_error> Method not allowed. Verify your Open WebUI host endpoint.")
                else:
                    print(f"chat_error> {exc}")
    finally:
        _ACTIVE_SESSION_CONTROLLER.reset(controller_token)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Marvel MCP Narrator CLI for Open WebUI-backed Marvel Multiverse RPG narration.",
        epilog=CLI_COMMANDS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model to use (defaults to config/env or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Open WebUI host URL (defaults to config/env or {DEFAULT_OPEN_WEBUI_HOST})",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI/OpenWebUI-compatible base URL for chat completions",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key sent in the Authorization header",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to TOML config file (default: ./narrator_config.toml if present)",
    )
    args = parser.parse_args()
    try:
        config = load_cli_config(config_path=args.config)
    except ValueError as exc:
        parser.error(str(exc))
    model = args.model or config["model"] or DEFAULT_MODEL
    host = args.host or config["host"] or DEFAULT_OPEN_WEBUI_HOST
    if args.base_url:
        base_url = args.base_url
    elif config["base_url"]:
        base_url = config["base_url"]
    else:
        base_url = host
    api_key = args.api_key if args.api_key is not None else config["api_key"]
    run_cli(model=model, host=host, base_url=base_url, api_key=api_key)


if __name__ == "__main__":
    main()
