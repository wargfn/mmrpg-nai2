"""Interactive Ollama CLI loop for local narrator/copilot experiments."""

from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError, roll_d616
from marvel_mcp_narrator.core.rules_database import query_rulebook_database

SYSTEM_PROMPT = (
    "You are a Marvel Multiverse RPG narrator copilot. "
    "Use deterministic tool outputs provided in context for dice and rules."
)
DEFAULT_MODEL = "llama3.3"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:3000"


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
    """Build an Open WebUI chat-completions endpoint URL from host/base URL."""
    normalized_host = normalize_open_webui_host(host).rstrip("/")
    return f"{normalized_host}/api/chat/completions"


def request_open_webui_chat(
    *,
    host: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str | None = None,
) -> str:
    """Send a chat request to Open WebUI and return assistant content."""
    endpoint = build_open_webui_chat_endpoint(host)
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
        "host": DEFAULT_OLLAMA_HOST,
        "api_key": None,
    }

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
        ollama_block = data.get("ollama", {})
        if isinstance(ollama_block, dict):
            model = ollama_block.get("model")
            host = ollama_block.get("host")
            api_key = ollama_block.get("api_key")
            if model:
                config["model"] = str(model)
            if host:
                config["host"] = str(host)
            if api_key:
                config["api_key"] = str(api_key)

    model_override = os.getenv("NARRATOR_MODEL")
    host_override = os.getenv("NARRATOR_OLLAMA_HOST")
    api_key_override = os.getenv("NARRATOR_API_KEY")
    if model_override:
        config["model"] = model_override
    if host_override:
        config["host"] = host_override
    if api_key_override:
        config["api_key"] = api_key_override
    return config


def _tool_injection(user_input: str) -> tuple[str | None, dict[str, Any] | str | None]:
    """Parse slash commands and return (tool_name, tool_output)."""
    stripped = user_input.strip()
    parts = stripped.split()
    if not parts:
        return None, None

    command = parts[0]

    if command == "/roll":
        edge = False
        trouble = False
        tn = None
        seen_edge = False
        seen_trouble = False
        seen_tn = False
        index = 1
        while index < len(parts):
            token = parts[index]
            if token == "--edge":
                if seen_edge:
                    raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
                seen_edge = True
                edge = True
                index += 1
                continue
            if token == "--trouble":
                if seen_trouble:
                    raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
                seen_trouble = True
                trouble = True
                index += 1
                continue
            if token == "--tn":
                if seen_tn:
                    raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
                seen_tn = True
                if index + 1 >= len(parts):
                    raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
                tn_value = parts[index + 1]
                if tn_value.startswith("--"):
                    raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
                try:
                    tn = int(tn_value)
                except ValueError as exc:
                    raise ValueError("Target number for --tn must be a positive integer.") from exc
                if tn <= 0:
                    raise ValueError("Target number for --tn must be a positive integer.")
                index += 2
                continue
            raise ValueError("Usage: /roll [--edge|--trouble] [--tn N]")
        return "resolve_d616_roll", roll_d616(edge=edge, trouble=trouble, target_number=tn)

    if command == "/rule":
        key = " ".join(parts[1:]).strip()
        if not key:
            raise ValueError("Usage: /rule <keyword>")
        return "lookup_rule", query_rulebook_database(key)

    return None, None


def run_cli(model: str, host: str = DEFAULT_OLLAMA_HOST, api_key: str | None = None) -> None:
    """Start an interactive Open WebUI-backed narrator loop."""
    print("Marvel MCP Narrator CLI")
    print("Type '/roll [--edge|--trouble] [--tn N]' or '/rule <keyword>' for deterministic tools.")
    print("Type 'exit' to quit.\n")

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("you> ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            return

        turn_start_index = len(messages)
        try:
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
            else:
                messages.append({"role": "user", "content": user_input})
        except (ValueError, D616ConfigurationError) as exc:
            print(f"tool_error> {exc}")
            continue

        try:
            final_content = request_open_webui_chat(
                host=host,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Marvel MCP Narrator CLI")
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model to use (defaults to config/env or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Open WebUI host URL (defaults to config/env or {DEFAULT_OLLAMA_HOST})",
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
    host = args.host or config["host"] or DEFAULT_OLLAMA_HOST
    api_key = args.api_key if args.api_key is not None else config["api_key"]
    run_cli(model=model, host=host, api_key=api_key)


if __name__ == "__main__":
    main()
