import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from unittest.mock import call

import discord

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.session_controller import GameSessionController
from marvel_mcp_narrator.interfaces.discord_bot import (
    BACKGROUND_SERVICE_ENV,
    DEFAULT_DISCORD_HISTORY_LIMIT,
    DEFAULT_DISCORD_COMMAND_PREFIX,
    DiscordBotConfig,
    NarratorDiscordCog,
    _build_rule_embed,
    _chunk_text,
    create_discord_bot,
    load_discord_bot_config,
    main,
    start_background_service,
)
from marvel_mcp_narrator.interfaces.cli import CLI_COMMANDS_HELP


class _FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeChannel:
    def __init__(self, channel_id: int, *, parent_id: int | None = None, guild=object()):
        self.id = channel_id
        self.parent_id = parent_id
        self.guild = guild
        self.sent_messages: list[dict] = []
        self.created_threads: list = []
        self._history_messages: list[SimpleNamespace] = []

    async def send(self, content=None, embed=None):
        self.sent_messages.append({"content": content, "embed": embed})

    def typing(self):
        return _FakeTyping()

    async def create_thread(self, *, name: str):
        thread = _FakeThread(self.id + 1000, parent_id=self.id, parent=self, guild=self.guild, name=name)
        self.created_threads.append(thread)
        return thread

    def history(self, *, limit: int):
        async def _iterate():
            for message in self._history_messages[:limit]:
                yield message

        return _iterate()


class _FakeContext:
    def __init__(self, *, author_id: int = 42, channel=None, message=None, interaction=None):
        self.sent_messages: list[dict] = []
        self.author = SimpleNamespace(id=author_id, display_name=f"User {author_id}")
        self.channel = channel or _FakeChannel(42)
        self.message = message
        self.interaction = interaction
        self.defer = AsyncMock()

    async def send(self, content=None, embed=None):
        self.sent_messages.append({"content": content, "embed": embed})


class _FakeThread:
    def __init__(
        self,
        channel_id: int,
        *,
        parent_id: int | None = None,
        parent=None,
        guild=object(),
        name: str = "Session",
        owner_id: int = 1,
    ):
        self.id = channel_id
        self.parent_id = parent_id
        self.parent = parent
        self.guild = guild
        self.owner_id = owner_id
        self.name = name
        self.sent_messages: list[dict] = []
        self._history_messages: list[SimpleNamespace] = []

    async def send(self, content=None, embed=None):
        self.sent_messages.append({"content": content, "embed": embed})

    def typing(self):
        return _FakeTyping()

    def history(self, *, limit: int):
        async def _iterate():
            for message in self._history_messages[:limit]:
                yield message

        return _iterate()


class DiscordBotConfigTests(unittest.TestCase):
    def test_main_help_includes_token_and_channel_flags(self):
        import contextlib
        import io

        stdout = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(stdout):
            main(["--help"])
        help_output = stdout.getvalue()
        self.assertIn("--token", help_output)
        self.assertIn("--campaign-channel-id", help_output)
        self.assertIn("--model", help_output)
        self.assertIn("--host", help_output)
        self.assertIn("--base-url", help_output)
        self.assertIn("--api-key", help_output)
        self.assertIn("--timeout", help_output)

    def test_load_discord_bot_config_reads_file_and_shared_openwebui_settings(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "narrator_config.toml"
            config_path.write_text(
                '[open_webui]\n'
                'model = "qwen2.5-coder"\n'
                'host = "http://remote:3000"\n'
                'llm_timeout_ms = 220\n'
                '[discord]\n'
                'token = "file-token"\n'
                'campaign_channel_id = 12345\n'
                'command_prefix = "?"\n'
                'history_limit = 12\n',
                encoding="utf-8",
            )
            config = load_discord_bot_config(str(config_path))

        self.assertEqual(config.token, "file-token")
        self.assertEqual(config.campaign_channel_id, 12345)
        self.assertEqual(config.command_prefix, "?")
        self.assertEqual(config.timeout, 0.22)
        self.assertEqual(config.model, "qwen2.5-coder")
        self.assertEqual(config.history_limit, 12)

    @patch.dict(
        "os.environ",
        {
            "DISCORD_BOT_TOKEN": "env-token",
            "NARRATOR_DISCORD_CAMPAIGN_CHANNEL_ID": "777",
            "NARRATOR_DISCORD_COMMAND_PREFIX": "$",
            "NARRATOR_DISCORD_HISTORY_LIMIT": "9",
            "NARRATOR_TIMEOUT": "33",
        },
        clear=True,
    )
    def test_load_discord_bot_config_prefers_env_over_file(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "narrator_config.toml"
            config_path.write_text(
                '[discord]\n'
                'token = "file-token"\n'
                'campaign_channel_id = 12\n'
                'command_prefix = "!"\n'
                'history_limit = 5\n',
                encoding="utf-8",
            )
            config = load_discord_bot_config(str(config_path))

        self.assertEqual(config.token, "env-token")
        self.assertEqual(config.campaign_channel_id, 777)
        self.assertEqual(config.command_prefix, "$")
        self.assertEqual(config.history_limit, 9)
        self.assertEqual(config.timeout, 33.0)

    def test_load_discord_bot_config_reads_legacy_timeout_when_llm_timeout_missing(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "narrator_config.toml"
            config_path.write_text(
                '[open_webui]\n'
                'timeout = 45\n'
                '[discord]\n'
                'token = "file-token"\n',
                encoding="utf-8",
            )
            config = load_discord_bot_config(str(config_path))

        self.assertEqual(config.timeout, 45.0)

    @patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token", "NARRATOR_DISCORD_COMMAND_PREFIX": "   "}, clear=True)
    def test_load_discord_bot_config_rejects_blank_env_prefix(self):
        with self.assertRaisesRegex(ValueError, "Discord environment command prefix must not be empty"):
            load_discord_bot_config()

    @patch.dict("os.environ", {}, clear=True)
    def test_load_discord_bot_config_requires_token(self):
        with self.assertRaisesRegex(ValueError, "Discord bot token is required"):
            load_discord_bot_config()

    @patch.dict(
        "os.environ",
        {
            "DISCORD_BOT_TOKEN": "env-token",
            "NARRATOR_DISCORD_CAMPAIGN_CHANNEL_ID": "777",
        },
        clear=True,
    )
    def test_load_discord_bot_config_prefers_cli_over_env_and_file(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "narrator_config.toml"
            config_path.write_text(
                '[discord]\n'
                'token = "file-token"\n'
                'campaign_channel_id = 12\n',
                encoding="utf-8",
            )
            config = load_discord_bot_config(
                str(config_path),
                token_override="cli-token",
                campaign_channel_id_override=999,
            )

        self.assertEqual(config.token, "cli-token")
        self.assertEqual(config.campaign_channel_id, 999)

    @patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token", "NARRATOR_TIMEOUT": "33"}, clear=True)
    def test_load_discord_bot_config_prefers_cli_timeout_over_env(self):
        config = load_discord_bot_config(timeout_override=9.5)

        self.assertEqual(config.timeout, 9.5)

    @patch.dict(
        "os.environ",
        {
            "DISCORD_BOT_TOKEN": "env-token",
            "NARRATOR_MODEL": "env-model",
            "NARRATOR_OPEN_WEBUI_HOST": "http://env-host:3000",
        },
        clear=True,
    )
    def test_load_discord_bot_config_prefers_cli_openwebui_overrides(self):
        config = load_discord_bot_config(
            model_override="cli-model",
            host_override="http://cli-host:3000",
            base_url_override="http://cli-host:3000/v1",
            api_key_override="cli-key",
        )

        self.assertEqual(config.model, "cli-model")
        self.assertEqual(config.host, "http://cli-host:3000")
        self.assertEqual(config.base_url, "http://cli-host:3000/v1")
        self.assertEqual(config.api_key, "cli-key")


class DiscordBotBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        character_roster.clear()
        self.tempdir = TemporaryDirectory()
        self.database = CampaignDatabase(Path(self.tempdir.name) / "campaign.db")
        self.controller = GameSessionController(campaign_database=self.database)
        self.config = DiscordBotConfig(
            token="test-token",
            campaign_channel_id=42,
            command_prefix=DEFAULT_DISCORD_COMMAND_PREFIX,
            timeout=15.0,
            history_limit=DEFAULT_DISCORD_HISTORY_LIMIT,
        )

    def tearDown(self):
        character_roster.clear()
        self.tempdir.cleanup()

    def test_create_discord_bot_binds_controller_and_intents(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        self.assertIs(bot.controller, self.controller)
        self.assertTrue(bot.intents.message_content)
        self.assertIn(DEFAULT_DISCORD_COMMAND_PREFIX, bot.command_prefix)
        self.assertIn("/", bot.command_prefix)

    def test_rule_command_registers_rules_text_alias(self):
        self.assertIn("rules", NarratorDiscordCog.rule.aliases)

    def test_seed_controller_is_not_reused_for_user_sessions(self):
        bot = create_discord_bot(self.config, controller=self.controller)

        session = bot.get_user_session(42)

        self.assertIsNot(session.controller, self.controller)

    def test_is_campaign_channel_accepts_parent_thread(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        self.assertTrue(bot.is_campaign_channel(SimpleNamespace(id=42, parent_id=None, guild=object())))
        self.assertTrue(bot.is_campaign_channel(_FakeThread(99, parent_id=42)))
        self.assertTrue(bot.is_campaign_channel(_FakeThread(99, parent_id=None, parent=SimpleNamespace(id=42, guild=object()))))
        self.assertFalse(bot.is_campaign_channel(SimpleNamespace(id=99, parent_id=42)))
        self.assertFalse(bot.is_campaign_channel(SimpleNamespace(id=50, parent_id=None)))

    def test_is_campaign_channel_rejects_private_threads(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        private_thread = SimpleNamespace(
            id=99,
            parent_id=42,
            guild=object(),
            type=discord.ChannelType.private_thread,
        )
        self.assertFalse(bot.is_campaign_channel(private_thread))

    def test_is_campaign_channel_rejects_non_guild_thread(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        self.assertFalse(bot.is_campaign_channel(_FakeThread(99, parent_id=42, guild=None, parent=SimpleNamespace(id=42, guild=None))))

    def test_is_campaign_channel_requires_explicit_configuration(self):
        config = DiscordBotConfig(token="test-token", campaign_channel_id=None)
        bot = create_discord_bot(config, controller=self.controller)
        self.assertFalse(bot.is_campaign_channel(SimpleNamespace(id=42, parent_id=None, guild=object())))

    def test_is_campaign_channel_rejects_non_guild_direct_match(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        self.assertFalse(bot.is_campaign_channel(SimpleNamespace(id=42, parent_id=None, guild=None)))

    async def test_setup_hook_adds_cog_without_syncing_tree(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()

        await bot.setup_hook()

        bot.add_cog.assert_awaited_once()
        self.assertIsInstance(bot.add_cog.await_args.args[0], NarratorDiscordCog)
        bot.tree.sync.assert_not_awaited()

    async def test_sync_commands_command_syncs_tree(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.tree.sync = AsyncMock(return_value=[object(), object()])
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        await cog.sync_commands.callback(cog, ctx)

        bot.tree.sync.assert_awaited_once_with()
        self.assertEqual(ctx.sent_messages[0]["content"], "Synced 2 application commands.")

    async def test_generate_channel_reply_maintains_history_per_channel(self):
        channel = _FakeChannel(42)
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator reply")

        response = await bot.generate_channel_reply(channel, 42, "Peter", "We investigate the lab.")

        self.assertEqual(response, "Narrator reply")
        history = bot.channel_histories[42]
        self.assertEqual(history[1]["content"], "Peter: We investigate the lab.")
        self.assertEqual(history[2]["content"], "Narrator reply")

    async def test_get_user_session_isolates_controllers_and_histories(self):
        bot = create_discord_bot(self.config, chat_request=lambda **_: "Narrator reply")

        first = bot.get_user_session(1001)
        second = bot.get_user_session(1002)

        self.assertIsNot(first.controller, second.controller)
        self.assertIsNot(first.controller.character_roster, second.controller.character_roster)
        self.assertIsNot(first.history, second.history)

    async def test_roll_command_uses_session_controller(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_user_controller = lambda *_: self.controller
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "roll_action", return_value={
            "dice_values": [3, 1, 5],
            "total_score": 12,
            "is_fantastic": True,
            "is_ultimate": False,
            "is_botch": False,
            "target_number": None,
        }) as mock_roll:
            await cog.roll.callback(cog, ctx, edges=1, troubles=0, modifier=2)

        mock_roll.assert_called_once_with(ability_modifier=2, edges=1, troubles=0)
        self.assertIn("Deterministic d616 Roll:", ctx.sent_messages[0]["content"])

    async def test_roll_command_defers_pending_slash_interaction(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_user_controller = lambda *_: self.controller
        cog = NarratorDiscordCog(bot)
        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: False))
        ctx = _FakeContext(interaction=interaction)

        await cog.roll.callback(cog, ctx, edges=0, troubles=0, modifier=0)

        ctx.defer.assert_awaited_once_with()

    async def test_rule_command_sends_embed(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_user_controller = lambda *_: self.controller
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "look_up_rule", return_value="## Rule Reference: Edge"):
            await cog.rule.callback(cog, ctx, query="edge")

        self.assertIsInstance(ctx.sent_messages[0]["embed"], discord.Embed)
        self.assertIn("Rule Lookup: edge", ctx.sent_messages[0]["embed"].title)

    async def test_attack_command_applies_rank_times_marvel_die_damage(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_user_controller = lambda *_: self.controller
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "apply_combat_damage", return_value={
            "target": {"name": "Hydra", "current_health": 63, "max_health": 75, "current_focus": 50, "max_focus": 50},
            "damage": {"rank": 3, "marvel_die_value": 4, "total_damage": 12},
        }) as mock_damage:
            await cog.attack.callback(cog, ctx, target="Hydra", rank=3, marvel_die=4)

        mock_damage.assert_called_once_with("Hydra", rank=3, marvel_die_value=4)
        self.assertIn("3 × 4 = 12", ctx.sent_messages[0]["content"])

    async def test_cog_app_command_error_sends_interaction_response(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        response = SimpleNamespace(is_done=lambda: False, send_message=AsyncMock())
        interaction = SimpleNamespace(response=response, followup=SimpleNamespace(send=AsyncMock()))

        await cog.cog_app_command_error(interaction, ValueError("boom"))

        response.send_message.assert_awaited_once_with("bot_error> boom")

    async def test_combat_status_command_formats_tracker_state(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_user_controller = lambda *_: self.controller
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "get_combat_state", return_value={
            "combatants": [
                {"name": "Hydra", "side": "enemy", "current_health": 30, "max_health": 50, "current_focus": 12, "max_focus": 20}
            ]
        }):
            await cog.combat_status.callback(cog, ctx)

        self.assertIn("Active Combat State:", ctx.sent_messages[0]["content"])
        self.assertIn("Hydra", ctx.sent_messages[0]["content"])

    async def test_combat_group_without_subcommand_shows_help(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        ctx = SimpleNamespace(invoked_subcommand=None, command=object(), send_help=AsyncMock())

        await cog.combat.callback(cog, ctx)

        ctx.send_help.assert_awaited_once_with(ctx.command)

    async def test_on_message_routes_narration_in_designated_channel(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
        bot.invoke = AsyncMock()
        bot.get_channel = lambda channel_id: None
        cog = NarratorDiscordCog(bot)
        channel = _FakeChannel(42)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=channel,
            content="What do I notice?",
            create_thread=channel.create_thread,
        )

        await cog.on_message(message)

        bot.get_context.assert_awaited_once_with(message)
        bot.invoke.assert_not_awaited()
        self.assertEqual(channel.created_threads[0].sent_messages[0]["content"], "Narrator response")
        self.assertIn(42, bot.channel_histories)
        self.assertEqual(bot.get_user_session(42).thread_id, channel.created_threads[0].id)

    async def test_on_message_redirects_user_to_existing_thread(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
        bot.invoke = AsyncMock()
        existing_thread = _FakeThread(1001, parent_id=42, owner_id=42)
        session = bot.get_user_session(42)
        session.thread_id = existing_thread.id
        bot.get_channel = lambda channel_id: existing_thread if channel_id == existing_thread.id else None
        cog = NarratorDiscordCog(bot)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=_FakeThread(1002, parent_id=42),
            content="What do I notice?",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        self.assertEqual(existing_thread.sent_messages[0]["content"], "Narrator response")

    async def test_on_message_rejects_other_users_thread_without_existing_session(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        other_thread = _FakeThread(1002, parent_id=42, owner_id=7)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=other_thread,
            content="What do I notice?",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        self.assertEqual(other_thread.sent_messages[0]["content"], "Use your dedicated session thread for narration.")

    async def test_on_message_rejects_owned_thread_outside_campaign_channel(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        owned_thread = _FakeThread(1003, parent_id=99, owner_id=42)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=owned_thread,
            content="What do I notice?",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        self.assertEqual(owned_thread.sent_messages, [])

    async def test_on_message_ignores_non_campaign_channels_and_commands(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        off_ctx = SimpleNamespace(valid=False)
        command_ctx = SimpleNamespace(valid=True)
        bot.get_context = AsyncMock(side_effect=[off_ctx, command_ctx])
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        off_channel = _FakeChannel(99)
        command_channel = _FakeChannel(42)
        off_message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=off_channel,
            content="Hello there",
            create_thread=off_channel.create_thread,
        )
        command_message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=command_channel,
            content="!roll",
            create_thread=command_channel.create_thread,
        )

        await cog.on_message(off_message)
        await cog.on_message(command_message)

        self.assertEqual(off_channel.sent_messages, [])
        self.assertEqual(command_channel.sent_messages, [])
        self.assertEqual(bot.get_context.await_args_list, [call(off_message), call(command_message)])
        bot.invoke.assert_awaited_once_with(command_ctx)

    async def test_on_message_routes_prefixed_commands_to_processor(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        ctx = SimpleNamespace(valid=True)
        bot.get_context = AsyncMock(return_value=ctx)
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        command_message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=_FakeChannel(42),
            content="!roll 1 0 2",
            create_thread=AsyncMock(),
        )

        await cog.on_message(command_message)

        bot.get_context.assert_awaited_once_with(command_message)
        bot.invoke.assert_awaited_once_with(ctx)
        self.assertEqual(command_message.channel.sent_messages, [])

    async def test_on_message_routes_cli_style_roll_command_locally(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_context = AsyncMock()
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=_FakeChannel(42),
            content="/roll --edge",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        bot.get_context.assert_not_awaited()
        bot.invoke.assert_not_awaited()
        self.assertIn("Deterministic d616 Roll:", message.channel.sent_messages[0]["content"])

    async def test_on_message_routes_cli_style_rules_command_locally(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_context = AsyncMock()
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=_FakeChannel(42),
            content="/rules teleport",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        bot.get_context.assert_not_awaited()
        bot.invoke.assert_not_awaited()
        self.assertEqual(message.channel.sent_messages[0]["embed"].title, "Rule Lookup: teleport")

    async def test_on_message_routes_help_command_locally(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_context = AsyncMock()
        bot.invoke = AsyncMock()
        cog = NarratorDiscordCog(bot)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=_FakeChannel(42),
            content="/help",
            create_thread=AsyncMock(),
        )

        await cog.on_message(message)

        bot.get_context.assert_not_awaited()
        bot.invoke.assert_not_awaited()
        self.assertEqual(message.channel.sent_messages[0]["content"], CLI_COMMANDS_HELP)

    async def test_on_message_reports_chat_backend_errors(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
        bot.generate_channel_reply = AsyncMock(side_effect=ConnectionError("offline"))
        bot.get_channel = lambda channel_id: None
        cog = NarratorDiscordCog(bot)
        channel = _FakeChannel(42)
        message = SimpleNamespace(
            author=SimpleNamespace(id=42, bot=False, display_name="Storm"),
            channel=channel,
            content="Tell me what I see.",
            create_thread=channel.create_thread,
        )

        await cog.on_message(message)

        self.assertEqual(channel.sent_messages[0]["content"], "chat_error> Connection refused. Is Open WebUI running?")

    async def test_clear_history_preserves_pinned_messages(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        channel = _FakeThread(1042, parent_id=42, parent=SimpleNamespace(id=42, guild=object()))
        command_message = SimpleNamespace(pinned=False, delete=AsyncMock())
        channel._history_messages = [
            command_message,
            SimpleNamespace(pinned=True, delete=AsyncMock()),
            SimpleNamespace(pinned=False, delete=AsyncMock()),
        ]
        session = bot.get_user_session(42)
        session.thread_id = channel.id
        session.history.append({"role": "user", "content": "Old message"})
        ctx = _FakeContext(author_id=42, channel=channel, message=command_message)

        await cog.clear_history.callback(cog, ctx, limit=10)

        self.assertEqual(ctx.sent_messages[0]["content"], "Cleared 1 non-pinned messages.")
        self.assertEqual(channel._history_messages[0].delete.await_count, 0)
        self.assertEqual(channel._history_messages[1].delete.await_count, 0)
        self.assertEqual(channel._history_messages[2].delete.await_count, 1)
        self.assertEqual(len(session.history), 1)
        self.assertIs(bot.channel_histories[42], session.history)

    async def test_clear_history_in_root_channel_resets_author_session(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        channel = _FakeChannel(42)
        session = bot.get_user_session(42)
        session.history.append({"role": "user", "content": "Old message"})
        ctx = _FakeContext(author_id=42, channel=channel)

        await cog.clear_history.callback(cog, ctx, limit=10)

        self.assertEqual(len(session.history), 1)
        self.assertIs(bot.channel_histories[42], session.history)

    def test_sessions_use_isolated_campaign_databases(self):
        with TemporaryDirectory() as tmpdir:
            shared_path = Path(tmpdir) / "campaign.db"
            bot = create_discord_bot(
                self.config,
                campaign_database=CampaignDatabase(shared_path),
            )

            first_path = bot.get_user_controller(1).campaign_database.path
            second_path = bot.get_user_controller(2).campaign_database.path

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.name, "campaign_user_1.db")
        self.assertEqual(second_path.name, "campaign_user_2.db")

    def test_default_user_campaign_database_path_uses_campaign_prefix(self):
        bot = create_discord_bot(self.config)

        path = bot._user_campaign_database_path(5)

        self.assertEqual(path.name, "campaign_user_5.db")


class DiscordBotHelperTests(unittest.TestCase):
    def test_chunk_text_splits_long_messages(self):
        payload = "A" * 2500
        chunks = _chunk_text(payload, limit=1000)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_build_rule_embed_uses_query_in_title(self):
        embed = _build_rule_embed("edge", "Rule text")
        self.assertEqual(embed.title, "Rule Lookup: edge")
        self.assertEqual(embed.description, "Rule text")


class DiscordBotServiceTests(unittest.TestCase):
    def test_start_background_service_spawns_detached_process_and_writes_pid(self):
        with TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "discord.pid"
            log_path = Path(tmpdir) / "discord.log"
            fake_process = SimpleNamespace(pid=4321)

            with patch("marvel_mcp_narrator.interfaces.discord_bot.subprocess.Popen", return_value=fake_process) as mock_popen:
                pid = start_background_service(
                    config_path="/tmp/narrator.toml",
                    token="cli-token",
                    campaign_channel_id=42,
                    model="cli-model",
                    host="http://cli-host:3000",
                    base_url="http://cli-host:3000/v1",
                    api_key="cli-key",
                    timeout=9.5,
                    pid_file=str(pid_path),
                    log_file=str(log_path),
                )

            self.assertEqual(pid, 4321)
            self.assertEqual(pid_path.read_text(encoding="utf-8"), "4321")
            command = mock_popen.call_args.args[0]
            self.assertTrue(command[0])
            self.assertEqual(command[1:3], ["-m", "marvel_mcp_narrator.interfaces.discord_bot"])
            self.assertIn("--config", command)
            self.assertIn("--token", command)
            self.assertIn("--campaign-channel-id", command)
            self.assertIn("--model", command)
            self.assertIn("--host", command)
            self.assertIn("--base-url", command)
            self.assertIn("--api-key", command)
            self.assertIn("--timeout", command)
            self.assertIn("--pid-file", command)
            self.assertIn("--log-file", command)
            self.assertEqual(mock_popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(mock_popen.call_args.kwargs["stderr"], subprocess.STDOUT)
            self.assertTrue(mock_popen.call_args.kwargs["start_new_session"])
            self.assertEqual(mock_popen.call_args.kwargs["env"][BACKGROUND_SERVICE_ENV], "1")

    def test_start_background_service_creates_missing_log_directory(self):
        with TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "discord.pid"
            log_path = Path(tmpdir) / "logs" / "nested" / "discord.log"
            fake_process = SimpleNamespace(pid=4321)

            with patch("marvel_mcp_narrator.interfaces.discord_bot.subprocess.Popen", return_value=fake_process):
                start_background_service(
                    config_path="/tmp/narrator.toml",
                    token="cli-token",
                    campaign_channel_id=42,
                    model="cli-model",
                    host="http://cli-host:3000",
                    base_url="http://cli-host:3000/v1",
                    api_key="cli-key",
                    timeout=9.5,
                    pid_file=str(pid_path),
                    log_file=str(log_path),
                )

            self.assertTrue(log_path.parent.exists())

    @patch("marvel_mcp_narrator.interfaces.discord_bot.start_background_service", return_value=9999)
    @patch("marvel_mcp_narrator.interfaces.discord_bot.load_discord_bot_config")
    def test_main_background_mode_launches_service_without_running_bot(self, mock_load_config, mock_start_background):
        main([
            "--background",
            "--config",
            "/tmp/narrator.toml",
            "--token",
            "cli-token",
            "--campaign-channel-id",
            "42",
            "--model",
            "cli-model",
            "--host",
            "http://cli-host:3000",
            "--base-url",
            "http://cli-host:3000/v1",
            "--api-key",
            "cli-key",
            "--timeout",
            "9.5",
            "--pid-file",
            "/tmp/discord.pid",
            "--log-file",
            "/tmp/discord.log",
        ])

        mock_start_background.assert_called_once_with(
            config_path="/tmp/narrator.toml",
            token="cli-token",
            campaign_channel_id=42,
            model="cli-model",
            host="http://cli-host:3000",
            base_url="http://cli-host:3000/v1",
            api_key="cli-key",
            timeout=9.5,
            pid_file="/tmp/discord.pid",
            log_file="/tmp/discord.log",
        )
        mock_load_config.assert_not_called()

    @patch("marvel_mcp_narrator.interfaces.discord_bot.create_discord_bot")
    @patch("marvel_mcp_narrator.interfaces.discord_bot.load_discord_bot_config")
    def test_main_passes_cli_overrides_to_config_loader(self, mock_load_config, mock_create_bot):
        mock_load_config.return_value = DiscordBotConfig(token="cli-token", campaign_channel_id=42)
        mock_bot = SimpleNamespace(run=lambda token: None)
        mock_create_bot.return_value = mock_bot

        with patch.object(mock_bot, "run") as mock_run:
            main([
                "--token",
                "cli-token",
                "--campaign-channel-id",
                "42",
                "--model",
                "cli-model",
                "--host",
                "http://cli-host:3000",
                "--base-url",
                "http://cli-host:3000/v1",
                "--api-key",
                "cli-key",
                "--timeout",
                "9.5",
            ])

        mock_load_config.assert_called_once_with(
            config_path=None,
            token_override="cli-token",
            campaign_channel_id_override=42,
            model_override="cli-model",
            host_override="http://cli-host:3000",
            base_url_override="http://cli-host:3000/v1",
            api_key_override="cli-key",
            timeout_override=9.5,
        )
        mock_create_bot.assert_called_once()
        mock_run.assert_called_once_with("cli-token")
