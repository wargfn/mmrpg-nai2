"""Interactive Ollama CLI loop for local narrator/copilot experiments."""

from __future__ import annotations

import argparse
import json
from typing import Any

import ollama

from marvel_mcp_narrator.core.d616_engine import roll_d616
from marvel_mcp_narrator.core.rules_database import RulesLookupError, lookup_rule_reference

SYSTEM_PROMPT = (
    "You are a Marvel Multiverse RPG narrator copilot. "
    "Use deterministic tool outputs provided in context for dice and rules."
)


def _tool_injection(user_input: str) -> tuple[str | None, dict[str, Any] | None]:
    """Parse slash commands and return (tool_name, tool_output)."""
    stripped = user_input.strip()
    if stripped.startswith("/roll"):
        parts = stripped.split()
        edge = "--edge" in parts
        trouble = "--trouble" in parts
        tn = None
        if "--tn" in parts:
            tn_index = parts.index("--tn")
            if tn_index + 1 >= len(parts):
                raise ValueError("Missing value for --tn")
            tn = int(parts[tn_index + 1])
        return "roll_d616", roll_d616(edge=edge, trouble=trouble, target_number=tn)

    if stripped.startswith("/rule"):
        key = stripped.replace("/rule", "", 1).strip()
        if not key:
            raise ValueError("Usage: /rule <reference_key>")
        return "lookup_rule_reference", lookup_rule_reference(key)

    return None, None


def run_cli(model: str) -> None:
    """Start an interactive Ollama-backed narrator loop."""
    print("Marvel MCP Narrator CLI")
    print("Type '/roll [--edge|--trouble] [--tn N]' or '/rule <key>' for deterministic tools.")
    print("Type 'exit' to quit.\n")

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("you> ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            return

        messages.append({"role": "user", "content": user_input})

        try:
            tool_name, tool_output = _tool_injection(user_input)
            if tool_name and tool_output is not None:
                payload = json.dumps(tool_output, ensure_ascii=False)
                print(f"tool[{tool_name}]> {payload}")
                messages.append(
                    {
                        "role": "system",
                        "content": f"Tool output ({tool_name}): {payload}",
                    }
                )
        except (ValueError, RulesLookupError) as exc:
            print(f"tool_error> {exc}")
            continue

        print("assistant> ", end="", flush=True)
        stream = ollama.chat(model=model, messages=messages, stream=True)

        chunks: list[str] = []
        for packet in stream:
            content = packet.get("message", {}).get("content", "")
            if content:
                print(content, end="", flush=True)
                chunks.append(content)
        print()

        messages.append({"role": "assistant", "content": "".join(chunks)})


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
