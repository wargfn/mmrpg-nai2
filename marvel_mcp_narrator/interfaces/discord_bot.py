"""Discord bot interface for the Marvel MCP Narrator."""

from __future__ import annotations

import argparse
import asyncio
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import discord
from discord.ext import commands

from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.rules_database import RulesLookupError
from marvel_mcp_narrator.core.session_controller import GameSessionController
from marvel_mcp_narrator.interfaces.cli import (
    DEFAULT_MODEL,
    DEFAULT_OPEN_WEBUI_HOST,
    DEFAULT_REQUEST_TIMEOUT,
    SYSTEM_PROMPT,
    _format_combat_state_result,
    _format_router_roll_result,
    get_active_character_context,
    get_rules_startup_context,
    get_startup_context,
    load_cli_config,
    request_open_webui_chat,
)

DEFAULT_DISCORD_COMMAND_PREFIX = "!"
DEFAULT_DISCORD_HISTORY_LIMIT = 24
MAX_DISCORD_MESSAGE_LENGTH = 2000


@dataclass(slots=True)
class DiscordBotConfig:
    """Runtime configuration for the Discord narrator interface."""

    token: str
    command_prefix: str = DEFAULT_DISCORD_COMMAND_PREFIX
    campaign_channel_id: int | None = None
    model: str = DEFAULT_MODEL
    host: str = DEFAULT_OPEN_WEBUI_HOST
    base_url: str | None = None
    api_key: str | None = None
    timeout: float = DEFAULT_REQUEST_TIMEOUT
    history_limit: int = DEFAULT_DISCORD_HISTORY_LIMIT


def _coerce_positive_float(value: object, *, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive number.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive number.")
    return parsed


def _coerce_optional_int(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return parsed


def _coerce_positive_int(value: object, *, field_name: str) -> int:
    parsed = _coerce_optional_int(value, field_name=field_name)
    if parsed is None:
        raise ValueError(f"{field_name} must be a positive integer.")
    return parsed


def _normalize_token(value: object) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _load_toml_config(config_path: str | None = None) -> dict[str, Any]:
    path: Path | None = None
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise ValueError(f"Configuration file not found: {path}")
    else:
        candidate = Path.cwd() / "narrator_config.toml"
        if candidate.exists():
            path = candidate
    if path is None:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_discord_bot_config(config_path: str | None = None) -> DiscordBotConfig:
    """Load Discord bot and shared Open WebUI settings."""
    shared_config = load_cli_config(config_path=config_path)
    raw_config = _load_toml_config(config_path=config_path)
    discord_block = raw_config.get("discord", {})
    if not isinstance(discord_block, dict):
        discord_block = {}

    token = _normalize_token(discord_block.get("token"))
    command_prefix = str(discord_block.get("command_prefix", DEFAULT_DISCORD_COMMAND_PREFIX)).strip()
    campaign_channel_id = _coerce_optional_int(
        discord_block.get("campaign_channel_id"), field_name="Discord campaign channel id"
    )
    history_limit_value = discord_block.get("history_limit", DEFAULT_DISCORD_HISTORY_LIMIT)
    history_limit = _coerce_positive_int(history_limit_value, field_name="Discord history limit")

    token_override = _normalize_token(os.getenv("NARRATOR_DISCORD_BOT_TOKEN") or os.getenv("DISCORD_BOT_TOKEN"))
    prefix_override = os.getenv("NARRATOR_DISCORD_COMMAND_PREFIX")
    channel_override = os.getenv("NARRATOR_DISCORD_CAMPAIGN_CHANNEL_ID")
    history_limit_override = os.getenv("NARRATOR_DISCORD_HISTORY_LIMIT")

    if token_override is not None:
        token = token_override
    if prefix_override is not None and prefix_override.strip():
        command_prefix = prefix_override.strip()
    if channel_override is not None:
        campaign_channel_id = _coerce_optional_int(channel_override, field_name="Discord campaign channel id")
    if history_limit_override is not None:
        history_limit = _coerce_positive_int(history_limit_override, field_name="Discord history limit")

    if token is None:
        raise ValueError(
            "Discord bot token is required. Set NARRATOR_DISCORD_BOT_TOKEN, DISCORD_BOT_TOKEN, or [discord].token."
        )

    if not command_prefix:
        command_prefix = DEFAULT_DISCORD_COMMAND_PREFIX

    base_url = shared_config["base_url"] if shared_config["base_url"] is not None else str(shared_config["host"])
    timeout = _coerce_positive_float(shared_config["timeout"], field_name="Discord/Open WebUI timeout")

    return DiscordBotConfig(
        token=token,
        command_prefix=command_prefix,
        campaign_channel_id=campaign_channel_id,
        model=str(shared_config["model"]),
        host=str(shared_config["host"]),
        base_url=str(base_url) if base_url is not None else None,
        api_key=str(shared_config["api_key"]) if shared_config["api_key"] is not None else None,
        timeout=timeout,
        history_limit=history_limit,
    )


def _format_attack_status(payload: dict[str, Any]) -> str:
    damage = payload["damage"]
    target = payload["target"]
    return "\n".join(
        [
            f"Combat Damage Applied: {target['name']}",
            f"- Formula: {damage['rank']} × {damage['marvel_die_value']} = {damage['total_damage']}",
            f"- Health: {target['current_health']}/{target['max_health']}",
            f"- Focus: {target['current_focus']}/{target['max_focus']}",
        ]
    )


def _build_rule_embed(query: str, result: str) -> discord.Embed:
    embed = discord.Embed(title=f"Rule Lookup: {query}", description=result[:4096], color=discord.Color.blue())
    if len(result) > 4096:
        embed.set_footer(text="Rule text truncated to fit Discord embed limits.")
    return embed


def _chunk_text(content: str, limit: int = MAX_DISCORD_MESSAGE_LENGTH) -> list[str]:
    if len(content) <= limit:
        return [content]
    chunks: list[str] = []
    remaining = content
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _build_channel_system_prompt(controller: GameSessionController) -> str:
    return "\n\n".join(
        [
            SYSTEM_PROMPT,
            get_rules_startup_context(),
            get_active_character_context(),
            _format_combat_state_result(controller.get_combat_state()),
            get_startup_context(controller.campaign_database),
        ]
    )


class DiscordNarratorBot(commands.Bot):
    """discord.py bot bound to the shared game session controller."""

    def __init__(
        self,
        *,
        config: DiscordBotConfig,
        controller: GameSessionController | None = None,
        chat_request: Callable[..., str] = request_open_webui_chat,
        campaign_database: CampaignDatabase | None = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.command_prefix, intents=intents)
        self.config = config
        self.controller = controller or GameSessionController(campaign_database=campaign_database)
        self.chat_request = chat_request
        self.channel_histories: dict[int, list[dict[str, str]]] = {}
        self.campaign_channel_id = config.campaign_channel_id

    async def setup_hook(self) -> None:
        await self.add_cog(NarratorDiscordCog(self))
        await self.tree.sync()

    @staticmethod
    def conversation_key(channel: discord.abc.Messageable) -> int:
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            raise ValueError("Discord channel does not expose an id.")
        return int(channel_id)

    def is_campaign_channel(self, channel: discord.abc.GuildChannel | discord.Thread | Any) -> bool:
        if self.campaign_channel_id is None:
            return True
        channel_id = getattr(channel, "id", None)
        parent_id = getattr(channel, "parent_id", None)
        return channel_id == self.campaign_channel_id or parent_id == self.campaign_channel_id

    def get_channel_history(self, channel: discord.abc.Messageable) -> list[dict[str, str]]:
        key = self.conversation_key(channel)
        history = self.channel_histories.get(key)
        if history is None:
            history = [{"role": "system", "content": _build_channel_system_prompt(self.controller)}]
            self.channel_histories[key] = history
        else:
            history[0]["content"] = _build_channel_system_prompt(self.controller)
        return history

    def _trim_history(self, history: list[dict[str, str]]) -> None:
        if len(history) <= self.config.history_limit + 1:
            return
        preserved_system = history[0]
        trimmed_tail = history[-self.config.history_limit :]
        history[:] = [preserved_system, *trimmed_tail]

    async def generate_channel_reply(self, channel: discord.abc.Messageable, user_name: str, content: str) -> str:
        history = self.get_channel_history(channel)
        history.append({"role": "user", "content": f"{user_name}: {content}"})
        self._trim_history(history)
        try:
            response = await asyncio.to_thread(
                self.chat_request,
                host=self.config.host,
                base_url=self.config.base_url or self.config.host,
                model=self.config.model,
                messages=list(history),
                api_key=self.config.api_key,
                timeout=self.config.timeout,
            )
        except Exception:
            history.pop()
            raise
        history.append({"role": "assistant", "content": response})
        self._trim_history(history)
        return response

    async def send_response(self, destination: Any, content: str) -> None:
        for chunk in _chunk_text(content):
            await destination.send(chunk)


class NarratorDiscordCog(commands.Cog):
    """Hybrid command and message handlers for narrator Discord sessions."""

    def __init__(self, bot: DiscordNarratorBot) -> None:
        self.bot = bot

    async def _send_rule_result(self, destination: Any, query: str, result: str) -> None:
        embed = _build_rule_embed(query, result)
        await destination.send(embed=embed)

    @commands.hybrid_command(name="roll", description="Resolve a deterministic d616 roll.")
    async def roll(
        self,
        ctx: commands.Context,
        edges: int = 0,
        troubles: int = 0,
        modifier: int = 0,
    ) -> None:
        payload = self.bot.controller.roll_action(
            ability_modifier=modifier,
            edges=edges,
            troubles=troubles,
        )
        await ctx.send(_format_router_roll_result(payload))

    @commands.hybrid_command(name="rule", description="Look up a rules reference or power.")
    async def rule(self, ctx: commands.Context, *, query: str) -> None:
        try:
            result = self.bot.controller.look_up_rule(query)
        except RulesLookupError as exc:
            await ctx.send(str(exc))
            return
        await self._send_rule_result(ctx, query, result)

    @commands.hybrid_command(name="attack", description="Apply rank × Marvel die damage to a tracked target.")
    async def attack(self, ctx: commands.Context, target: str, rank: int, marvel_die: int) -> None:
        payload = self.bot.controller.apply_combat_damage(target, rank=rank, marvel_die_value=marvel_die)
        await ctx.send(_format_attack_status(payload))

    @commands.hybrid_group(name="combat", description="Combat state commands.")
    async def combat(self, ctx: commands.Context) -> None:
        await ctx.send(_format_combat_state_result(self.bot.controller.get_combat_state()))

    @combat.command(name="status", description="Show tracked combatant health pools.")
    async def combat_status(self, ctx: commands.Context) -> None:
        await ctx.send(_format_combat_state_result(self.bot.controller.get_combat_state()))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.content.startswith(self.bot.command_prefix):
            await self.bot.process_commands(message)
            return
        if not self.bot.is_campaign_channel(message.channel):
            return
        async with message.channel.typing():
            response = await self.bot.generate_channel_reply(message.channel, message.author.display_name, message.content)
        await self.bot.send_response(message.channel, response)


def create_discord_bot(
    config: DiscordBotConfig,
    *,
    controller: GameSessionController | None = None,
    chat_request: Callable[..., str] = request_open_webui_chat,
    campaign_database: CampaignDatabase | None = None,
) -> DiscordNarratorBot:
    """Create a configured Discord narrator bot instance."""
    return DiscordNarratorBot(
        config=config,
        controller=controller,
        chat_request=chat_request,
        campaign_database=campaign_database,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the Discord bot CLI parser."""
    parser = argparse.ArgumentParser(
        description="Marvel MCP Narrator Discord bot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to TOML config file (default: ./narrator_config.toml if present)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the Discord narrator bot."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config = load_discord_bot_config(config_path=args.config)
    bot = create_discord_bot(config)
    bot.run(config.token)


def run() -> None:
    """Compatibility entry point for interface launchers."""
    main()


if __name__ == "__main__":
    main()
