import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.session_controller import GameSessionController
from marvel_mcp_narrator.interfaces.discord_bot import (
    DEFAULT_DISCORD_HISTORY_LIMIT,
    DEFAULT_DISCORD_COMMAND_PREFIX,
    DiscordBotConfig,
    NarratorDiscordCog,
    _build_rule_embed,
    _chunk_text,
    create_discord_bot,
    load_discord_bot_config,
)


class _FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeChannel:
    def __init__(self, channel_id: int, *, parent_id: int | None = None):
        self.id = channel_id
        self.parent_id = parent_id
        self.sent_messages: list[dict] = []

    async def send(self, content=None, embed=None):
        self.sent_messages.append({"content": content, "embed": embed})

    def typing(self):
        return _FakeTyping()


class _FakeContext:
    def __init__(self):
        self.sent_messages: list[dict] = []

    async def send(self, content=None, embed=None):
        self.sent_messages.append({"content": content, "embed": embed})


class DiscordBotConfigTests(unittest.TestCase):
    def test_load_discord_bot_config_reads_file_and_shared_openwebui_settings(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "narrator_config.toml"
            config_path.write_text(
                '[open_webui]\n'
                'model = "qwen2.5-coder"\n'
                'host = "http://remote:3000"\n'
                'timeout = 45\n'
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
        self.assertEqual(config.timeout, 45.0)
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

    @patch.dict("os.environ", {}, clear=True)
    def test_load_discord_bot_config_requires_token(self):
        with self.assertRaisesRegex(ValueError, "Discord bot token is required"):
            load_discord_bot_config()


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
        self.assertEqual(bot.command_prefix, DEFAULT_DISCORD_COMMAND_PREFIX)

    def test_is_campaign_channel_accepts_parent_thread(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        self.assertTrue(bot.is_campaign_channel(SimpleNamespace(id=42, parent_id=None)))
        self.assertTrue(bot.is_campaign_channel(SimpleNamespace(id=99, parent_id=42)))
        self.assertFalse(bot.is_campaign_channel(SimpleNamespace(id=50, parent_id=None)))

    async def test_setup_hook_adds_cog_and_syncs_tree(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()

        await bot.setup_hook()

        bot.add_cog.assert_awaited_once()
        self.assertIsInstance(bot.add_cog.await_args.args[0], NarratorDiscordCog)
        bot.tree.sync.assert_awaited_once_with()

    async def test_generate_channel_reply_maintains_history_per_channel(self):
        channel = _FakeChannel(42)
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator reply")

        response = await bot.generate_channel_reply(channel, "Peter", "We investigate the lab.")

        self.assertEqual(response, "Narrator reply")
        history = bot.channel_histories[42]
        self.assertEqual(history[1]["content"], "Peter: We investigate the lab.")
        self.assertEqual(history[2]["content"], "Narrator reply")

    async def test_roll_command_uses_session_controller(self):
        bot = create_discord_bot(self.config, controller=self.controller)
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

    async def test_rule_command_sends_embed(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "look_up_rule", return_value="## Rule Reference: Edge"):
            await cog.rule.callback(cog, ctx, query="edge")

        self.assertIsInstance(ctx.sent_messages[0]["embed"], discord.Embed)
        self.assertIn("Rule Lookup: edge", ctx.sent_messages[0]["embed"].title)

    async def test_attack_command_applies_rank_times_marvel_die_damage(self):
        bot = create_discord_bot(self.config, controller=self.controller)
        cog = NarratorDiscordCog(bot)
        ctx = _FakeContext()

        with patch.object(self.controller, "apply_combat_damage", return_value={
            "target": {"name": "Hydra", "current_health": 63, "max_health": 75, "current_focus": 50, "max_focus": 50},
            "damage": {"rank": 3, "marvel_die_value": 4, "total_damage": 12},
        }) as mock_damage:
            await cog.attack.callback(cog, ctx, target="Hydra", rank=3, marvel_die=4)

        mock_damage.assert_called_once_with("Hydra", rank=3, marvel_die_value=4)
        self.assertIn("3 × 4 = 12", ctx.sent_messages[0]["content"])

    async def test_combat_status_command_formats_tracker_state(self):
        bot = create_discord_bot(self.config, controller=self.controller)
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

    async def test_on_message_routes_narration_in_designated_channel(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        cog = NarratorDiscordCog(bot)
        channel = _FakeChannel(42)
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, display_name="Storm"),
            channel=channel,
            content="What do I notice?",
        )

        await cog.on_message(message)

        self.assertEqual(channel.sent_messages[0]["content"], "Narrator response")
        self.assertIn(42, bot.channel_histories)

    async def test_on_message_ignores_non_campaign_channels_and_commands(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.process_commands = AsyncMock()
        cog = NarratorDiscordCog(bot)
        off_channel = _FakeChannel(99)
        command_channel = _FakeChannel(42)
        off_message = SimpleNamespace(
            author=SimpleNamespace(bot=False, display_name="Storm"),
            channel=off_channel,
            content="Hello there",
        )
        command_message = SimpleNamespace(
            author=SimpleNamespace(bot=False, display_name="Storm"),
            channel=command_channel,
            content="!roll",
        )

        await cog.on_message(off_message)
        await cog.on_message(command_message)

        self.assertEqual(off_channel.sent_messages, [])
        self.assertEqual(command_channel.sent_messages, [])
        bot.process_commands.assert_awaited_once_with(command_message)

    async def test_on_message_routes_prefixed_commands_to_processor(self):
        bot = create_discord_bot(self.config, controller=self.controller, chat_request=lambda **_: "Narrator response")
        bot.process_commands = AsyncMock()
        cog = NarratorDiscordCog(bot)
        command_message = SimpleNamespace(
            author=SimpleNamespace(bot=False, display_name="Storm"),
            channel=_FakeChannel(42),
            content="!roll 1 0 2",
        )

        await cog.on_message(command_message)

        bot.process_commands.assert_awaited_once_with(command_message)
        self.assertEqual(command_message.channel.sent_messages, [])


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
