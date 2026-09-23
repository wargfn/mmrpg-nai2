"""Discord bot interface for the Marvel MCP Narrator."""

from __future__ import annotations

import atexit
import argparse
import asyncio
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import discord
from discord.ext import commands

from marvel_mcp_narrator.core.character_state import CharacterRoster
from marvel_mcp_narrator.core.memory.campaign_db import CAMPAIGN_DB_PATH, CampaignDatabase
from marvel_mcp_narrator.core.rules_database import RulesLookupError
from marvel_mcp_narrator.core.session_controller import GameSessionController
from marvel_mcp_narrator.interfaces.cli import (
    CLI_COMMANDS_HELP,
    DEFAULT_MODEL,
    DEFAULT_OPEN_WEBUI_HOST,
    DEFAULT_REQUEST_TIMEOUT,
    SYSTEM_PROMPT,
    _format_combat_state_result,
    _format_router_roll_result,
    _route_intent_command,
    get_active_character_context,
    get_rules_startup_context,
    get_startup_context,
    load_cli_config,
    request_open_webui_chat,
)

DEFAULT_DISCORD_COMMAND_PREFIX = "!"
DEFAULT_DISCORD_HISTORY_LIMIT = 24
MAX_DISCORD_MESSAGE_LENGTH = 2000
BACKGROUND_SERVICE_ENV = "NARRATOR_DISCORD_BACKGROUND_SERVICE"


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


@dataclass(slots=True)
class DiscordUserSession:
    user_id: int
    controller: GameSessionController
    history: list[dict[str, str]] = field(default_factory=list)
    thread_id: int | None = None


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


def _normalize_command_prefix(value: object, *, source_name: str, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise ValueError(f"{source_name} command prefix is required.")
        return default
    prefix = str(value).strip()
    if not prefix:
        raise ValueError(f"{source_name} command prefix must not be empty.")
    return prefix


def _build_command_prefixes(primary_prefix: str) -> tuple[str, ...]:
    prefixes = [primary_prefix]
    if "/" not in prefixes:
        prefixes.append("/")
    return tuple(prefixes)


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


def load_discord_bot_config(
    config_path: str | None = None,
    *,
    token_override: str | None = None,
    campaign_channel_id_override: int | None = None,
    timeout_override: float | None = None,
) -> DiscordBotConfig:
    """Load Discord bot and shared Open WebUI settings."""
    shared_config = load_cli_config(config_path=config_path)
    raw_config = _load_toml_config(config_path=config_path)
    discord_block = raw_config.get("discord", {})
    if not isinstance(discord_block, dict):
        discord_block = {}

    token = _normalize_token(discord_block.get("token"))
    if "command_prefix" in discord_block:
        command_prefix = _normalize_command_prefix(
            discord_block.get("command_prefix"), source_name="Discord config"
        )
    else:
        command_prefix = DEFAULT_DISCORD_COMMAND_PREFIX
    campaign_channel_id = _coerce_optional_int(
        discord_block.get("campaign_channel_id"), field_name="Discord campaign channel id"
    )
    history_limit_value = discord_block.get("history_limit", DEFAULT_DISCORD_HISTORY_LIMIT)
    history_limit = _coerce_positive_int(history_limit_value, field_name="Discord history limit")

    env_token_override = _normalize_token(os.getenv("NARRATOR_DISCORD_BOT_TOKEN") or os.getenv("DISCORD_BOT_TOKEN"))
    env_prefix_override = os.getenv("NARRATOR_DISCORD_COMMAND_PREFIX")
    env_channel_override = os.getenv("NARRATOR_DISCORD_CAMPAIGN_CHANNEL_ID")
    env_history_limit_override = os.getenv("NARRATOR_DISCORD_HISTORY_LIMIT")

    if env_token_override is not None:
        token = env_token_override
    if env_prefix_override is not None:
        command_prefix = _normalize_command_prefix(env_prefix_override, source_name="Discord environment")
    if env_channel_override is not None:
        campaign_channel_id = _coerce_optional_int(env_channel_override, field_name="Discord campaign channel id")
    if env_history_limit_override is not None:
        history_limit = _coerce_positive_int(env_history_limit_override, field_name="Discord history limit")
    if token_override is not None:
        token = _normalize_token(token_override)
    if campaign_channel_id_override is not None:
        campaign_channel_id = _coerce_optional_int(
            campaign_channel_id_override,
            field_name="Discord campaign channel id",
        )
    if timeout_override is not None:
        shared_config["timeout"] = _coerce_positive_float(timeout_override, field_name="Discord/Open WebUI timeout")

    if token is None:
        raise ValueError(
            "Discord bot token is required. Set NARRATOR_DISCORD_BOT_TOKEN, DISCORD_BOT_TOKEN, or [discord].token."
        )

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
            get_active_character_context(controller.character_roster),
            _format_combat_state_result(controller.get_combat_state()),
            get_startup_context(controller.campaign_database),
        ]
    )


def _format_chat_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(exc, PermissionError):
        return str(exc)
    if isinstance(exc, ConnectionError):
        return "chat_error> Connection refused. Is Open WebUI running?"
    if status_code == 405:
        return "chat_error> Method not allowed. Verify your Open WebUI host endpoint."
    return f"chat_error> {exc}"


def _write_pid_file(pid_file: str | None, *, pid: int | None = None) -> None:
    if not pid_file:
        return
    Path(pid_file).expanduser().write_text(str(os.getpid() if pid is None else pid), encoding="utf-8")


def _cleanup_pid_file(pid_file: str | None) -> None:
    if not pid_file:
        return
    path = Path(pid_file).expanduser()
    try:
        if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except FileNotFoundError:
        return


def start_background_service(
    *,
    config_path: str | None = None,
    token: str | None = None,
    campaign_channel_id: int | None = None,
    timeout: float | None = None,
    pid_file: str | None = None,
    log_file: str | None = None,
) -> int:
    """Launch the Discord bot as a detached background process."""
    command = [sys.executable, "-m", "marvel_mcp_narrator.interfaces.discord_bot"]
    if config_path:
        command.extend(["--config", config_path])
    if token:
        command.extend(["--token", token])
    if campaign_channel_id is not None:
        command.extend(["--campaign-channel-id", str(campaign_channel_id)])
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    if pid_file:
        command.extend(["--pid-file", pid_file])
    if log_file:
        command.extend(["--log-file", log_file])

    env = os.environ.copy()
    env[BACKGROUND_SERVICE_ENV] = "1"

    log_path = os.devnull if log_file is None else str(Path(log_file).expanduser())
    if log_file is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    except Exception:
        log_handle.close()
        raise
    log_handle.close()
    _write_pid_file(pid_file, pid=process.pid)
    return int(process.pid)


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
        super().__init__(command_prefix=_build_command_prefixes(config.command_prefix), intents=intents)
        self.config = config
        self.controller = controller
        self.chat_request = chat_request
        self.campaign_channel_id = config.campaign_channel_id
        self.channel_histories: dict[int, list[dict[str, str]]] = {}
        self._user_sessions: dict[int, DiscordUserSession] = {}
        self._seed_controller = controller
        self._campaign_database = campaign_database

    async def setup_hook(self) -> None:
        await self.add_cog(NarratorDiscordCog(self))

    @staticmethod
    def _user_campaign_database_path(user_id: int) -> Path:
        return CAMPAIGN_DB_PATH.parent / "discord_sessions" / f"campaign_user_{user_id}.db"

    def _campaign_database_for_user(self, user_id: int) -> CampaignDatabase:
        if self._campaign_database is None:
            return CampaignDatabase(self._user_campaign_database_path(user_id))
        base_path = self._campaign_database.path
        isolated_path = base_path.with_name(f"{base_path.stem}_user_{user_id}{base_path.suffix}")
        return CampaignDatabase(isolated_path)

    def _build_controller_for_user(self, user_id: int) -> GameSessionController:
        roster = CharacterRoster()
        database = self._campaign_database_for_user(user_id)
        rules_database = None if self._seed_controller is None else self._seed_controller.rules_database
        return GameSessionController(
            rules_database=rules_database,
            campaign_database=database,
            character_roster_store=roster,
        )

    def get_user_session(self, user_id: int) -> DiscordUserSession:
        session = self._user_sessions.get(user_id)
        if session is None:
            controller = self._build_controller_for_user(user_id)
            session = DiscordUserSession(
                user_id=user_id,
                controller=controller,
                history=[{"role": "system", "content": _build_channel_system_prompt(controller)}],
            )
            self._user_sessions[user_id] = session
            self.channel_histories[user_id] = session.history
        else:
            session.history[0]["content"] = _build_channel_system_prompt(session.controller)
        return session

    def get_user_controller(self, user_id: int) -> GameSessionController:
        return self.get_user_session(user_id).controller

    def get_session_for_channel(self, channel: discord.abc.Messageable | Any) -> DiscordUserSession | None:
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            return None
        for session in self._user_sessions.values():
            if session.thread_id == channel_id:
                return session
        return None

    async def ensure_user_thread(self, message: discord.Message) -> discord.abc.Messageable:
        user_id = int(message.author.id)
        session = self.get_user_session(user_id)
        channel = message.channel
        if getattr(channel, "id", None) != self.campaign_channel_id:
            current_channel_id = getattr(channel, "id", None)
            if session.thread_id is None:
                if getattr(channel, "owner_id", None) == user_id and self.is_campaign_channel(channel):
                    session.thread_id = current_channel_id
                    return channel
                raise PermissionError("Use your dedicated session thread for narration.")
            if session.thread_id == current_channel_id:
                return channel
            existing_thread = self.get_channel(session.thread_id)
            if existing_thread is not None:
                return existing_thread
            raise PermissionError("Use your dedicated session thread for narration.")

        if session.thread_id is not None:
            existing_thread = self.get_channel(session.thread_id)
            if existing_thread is not None:
                return existing_thread

        thread = await message.create_thread(name=f"{message.author.display_name} Session")
        session.thread_id = getattr(thread, "id", None)
        return thread

    @staticmethod
    def _is_supported_campaign_root_channel(channel: Any) -> bool:
        if getattr(channel, "guild", None) is None:
            return False
        channel_type = getattr(channel, "type", None)
        if channel_type is None:
            return True
        return channel_type in {
            discord.ChannelType.text,
            discord.ChannelType.news,
        }

    @staticmethod
    def _is_supported_campaign_thread(channel: Any) -> bool:
        channel_type = getattr(channel, "type", None)
        if channel_type is not None:
            return channel_type in {
                discord.ChannelType.public_thread,
                discord.ChannelType.news_thread,
            }
        has_thread_metadata = any(
            getattr(channel, attribute, None) is not None
            for attribute in ("owner_id", "archive_timestamp", "message_count")
        )
        return has_thread_metadata and "thread" in type(channel).__name__.lower()

    @staticmethod
    def conversation_key(channel: discord.abc.Messageable) -> int:
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            raise ValueError("Discord channel does not expose an id.")
        return int(channel_id)

    def is_campaign_channel(self, channel: discord.abc.GuildChannel | discord.Thread | Any) -> bool:
        if self.campaign_channel_id is None:
            return False
        channel_id = getattr(channel, "id", None)
        if channel_id == self.campaign_channel_id and self._is_supported_campaign_root_channel(channel):
            return True
        if not self._is_supported_campaign_thread(channel):
            return False
        parent_id = getattr(channel, "parent_id", None)
        parent = getattr(channel, "parent", None)
        if getattr(channel, "guild", None) is None and getattr(parent, "guild", None) is None:
            return False
        parent_channel_id = getattr(parent, "id", None)
        return parent_id == self.campaign_channel_id or parent_channel_id == self.campaign_channel_id

    def _trim_history(self, history: list[dict[str, str]]) -> None:
        if len(history) <= self.config.history_limit + 1:
            return
        preserved_system = history[0]
        trimmed_tail = history[-self.config.history_limit :]
        history[:] = [preserved_system, *trimmed_tail]

    def reset_session_history(self, session: DiscordUserSession) -> None:
        session.history[:] = [{"role": "system", "content": _build_channel_system_prompt(session.controller)}]
        self.channel_histories[session.user_id] = session.history

    async def generate_channel_reply(
        self,
        channel: discord.abc.Messageable,
        user_id: int,
        user_name: str,
        content: str,
    ) -> str:
        session = self.get_user_session(user_id)
        history = session.history
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

    @staticmethod
    def _author_id(actor: Any) -> int:
        return int(getattr(actor, "id"))

    def _controller_for_actor(self, actor: Any) -> GameSessionController:
        return self.bot.get_user_controller(self._author_id(actor))

    @staticmethod
    async def _maybe_defer(ctx: commands.Context) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is None:
            return
        response = getattr(interaction, "response", None)
        is_done = getattr(response, "is_done", None)
        if callable(is_done) and is_done():
            return
        await ctx.defer()

    async def _send_rule_result(self, destination: Any, query: str, result: str) -> None:
        embed = _build_rule_embed(query, result)
        await destination.send(embed=embed)

    async def _route_text_command(self, message: discord.Message) -> bool:
        content = str(getattr(message, "content", "")).strip()
        if not content.startswith("/"):
            return False
        if content.lower() == "/help":
            await self.bot.send_response(message.channel, CLI_COMMANDS_HELP)
            return True
        try:
            routed = _route_intent_command(content, session_controller=self._controller_for_actor(message.author))
        except Exception as exc:
            await message.channel.send(self._format_command_error(exc))
            return True
        if routed is None:
            return False
        tool_name, payload = routed
        if tool_name == "lookup_rule":
            query = content.split(maxsplit=1)[1] if " " in content else ""
            await self._send_rule_result(message.channel, query, str(payload))
            return True
        await self.bot.send_response(message.channel, str(payload))
        return True

    @staticmethod
    def _format_command_error(error: Exception) -> str:
        if isinstance(error, commands.MissingPermissions):
            return "bot_error> You do not have permission to use this command."
        if isinstance(error, commands.NoPrivateMessage):
            return "bot_error> This command can only be used in a server channel."
        if isinstance(error, (RulesLookupError, ValueError, KeyError)):
            return f"bot_error> {error}"
        return f"bot_error> {error}"

    async def _send_interaction_error(self, interaction: discord.Interaction, content: str) -> None:
        response = getattr(interaction, "response", None)
        is_done = getattr(response, "is_done", None)
        if callable(is_done) and not is_done():
            await interaction.response.send_message(content)
            return
        followup = getattr(interaction, "followup", None)
        if followup is not None:
            await followup.send(content)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        resolved = getattr(error, "original", error)
        message = self._format_command_error(resolved)
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None:
            await self._send_interaction_error(interaction, message)
            return
        await ctx.send(message)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        resolved = getattr(error, "original", error)
        await self._send_interaction_error(interaction, self._format_command_error(resolved))

    @commands.hybrid_command(name="roll", description="Resolve a deterministic d616 roll.")
    async def roll(
        self,
        ctx: commands.Context,
        edges: int = 0,
        troubles: int = 0,
        modifier: int = 0,
    ) -> None:
        await self._maybe_defer(ctx)
        payload = self._controller_for_actor(ctx.author).roll_action(
            ability_modifier=modifier,
            edges=edges,
            troubles=troubles,
        )
        await ctx.send(_format_router_roll_result(payload))

    @commands.hybrid_command(name="rule", aliases=["rules"], description="Look up a rules reference or power.")
    async def rule(self, ctx: commands.Context, *, query: str) -> None:
        await self._maybe_defer(ctx)
        try:
            result = self._controller_for_actor(ctx.author).look_up_rule(query)
        except RulesLookupError as exc:
            await ctx.send(str(exc))
            return
        await self._send_rule_result(ctx, query, result)

    @commands.hybrid_command(name="attack", description="Apply rank × Marvel die damage to a tracked target.")
    async def attack(self, ctx: commands.Context, target: str, rank: int, marvel_die: int) -> None:
        await self._maybe_defer(ctx)
        payload = self._controller_for_actor(ctx.author).apply_combat_damage(target, rank=rank, marvel_die_value=marvel_die)
        await ctx.send(_format_attack_status(payload))

    @commands.hybrid_group(name="combat", description="Combat state commands.")
    async def combat(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @combat.command(name="status", description="Show tracked combatant health pools.", with_app_command=True)
    async def combat_status(self, ctx: commands.Context) -> None:
        await self._maybe_defer(ctx)
        await ctx.send(_format_combat_state_result(self._controller_for_actor(ctx.author).get_combat_state()))

    @commands.hybrid_command(name="clear_history", aliases=["clear"], description="Clear recent channel history.")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def clear_history(self, ctx: commands.Context, limit: int = 100) -> None:
        await self._maybe_defer(ctx)
        if limit < 1:
            raise ValueError("History clear limit must be a positive integer.")
        deleted = 0
        command_message = getattr(ctx, "message", None)
        async for message in ctx.channel.history(limit=limit):
            if command_message is not None and message is command_message:
                continue
            if getattr(message, "pinned", False):
                continue
            await message.delete()
            deleted += 1
        session = self.bot.get_session_for_channel(ctx.channel)
        if session is None and self.bot.is_campaign_channel(ctx.channel):
            session = self.bot.get_user_session(self._author_id(ctx.author))
        if session is not None:
            self.bot.reset_session_history(session)
        await ctx.send(f"Cleared {deleted} non-pinned messages.")

    @commands.command(name="sync-commands", hidden=True)
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def sync_commands(self, ctx: commands.Context) -> None:
        synced = await self.bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} application commands.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if await self._route_text_command(message):
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            await self.bot.invoke(ctx)
            return
        if not self.bot.is_campaign_channel(message.channel):
            return
        try:
            target_channel = await self.bot.ensure_user_thread(message)
            async with target_channel.typing():
                response = await self.bot.generate_channel_reply(
                    target_channel,
                    self._author_id(message.author),
                    message.author.display_name,
                    message.content,
                )
        except Exception as exc:
            await message.channel.send(_format_chat_error(exc))
            return
        await self.bot.send_response(target_channel, response)


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
    parser.add_argument(
        "--token",
        default=None,
        help="Discord bot token (overrides environment variables and config file).",
    )
    parser.add_argument(
        "--campaign-channel-id",
        type=int,
        default=None,
        help="Discord channel id for freeform campaign narration; if omitted, natural-language narration is disabled.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="HTTP timeout in seconds for Discord bot Open WebUI requests.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Launch the Discord bot as a detached background service.",
    )
    parser.add_argument(
        "--pid-file",
        default=None,
        help="Optional pid file path for foreground or background service runs.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file for background service stdout/stderr (defaults to os.devnull).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the Discord narrator bot."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.background and os.getenv(BACKGROUND_SERVICE_ENV) != "1":
        start_background_service(
            config_path=args.config,
            token=args.token,
            campaign_channel_id=args.campaign_channel_id,
            timeout=args.timeout,
            pid_file=args.pid_file,
            log_file=args.log_file,
        )
        return
    if args.pid_file:
        _write_pid_file(args.pid_file)
        atexit.register(_cleanup_pid_file, args.pid_file)
    config = load_discord_bot_config(
        config_path=args.config,
        token_override=args.token,
        campaign_channel_id_override=args.campaign_channel_id,
        timeout_override=args.timeout,
    )
    bot = create_discord_bot(config)
    bot.run(config.token)


def run() -> None:
    """Compatibility entry point for interface launchers."""
    main()


if __name__ == "__main__":
    main()
