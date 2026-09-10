"""Interactive Ollama CLI loop for local narrator/copilot experiments."""

from __future__ import annotations

import argparse
import json
from typing import Any

import ollama

from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError, roll_d616
from marvel_mcp_narrator.core.rules_database import query_rulebook_database

SYSTEM_PROMPT = (
    "You are a Marvel Multiverse RPG narrator copilot. "
    "Use deterministic tool outputs provided in context for dice and rules."
)


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


def run_cli(model: str) -> None:
    """Start an interactive Ollama-backed narrator loop."""
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

        chunks: list[str] = []
        try:
            stream = ollama.chat(model=model, messages=list(messages), stream=True)
            packets = [stream] if isinstance(stream, dict) else stream
            print("assistant> ", end="", flush=True)

            for packet in packets:
                content = packet.get("message", {}).get("content", "")
                if content:
                    print(content, end="", flush=True)
                    chunks.append(content)
            print()

            final_content = "".join(chunks)
            if final_content:
                messages.append({"role": "assistant", "content": final_content})
        except (ollama.RequestError, ollama.ResponseError) as exc:
            if chunks:
                print()
            del messages[turn_start_index:]
            print(f"chat_error> {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Marvel MCP Narrator CLI")
    parser.add_argument(
        "--model",
        default="llama3.3",
        help="Local Ollama model to use (default: llama3.3)",
    )
    args = parser.parse_args()
    run_cli(model=args.model)


if __name__ == "__main__":
    main()
