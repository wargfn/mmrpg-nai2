import contextlib
import io
import unittest
import tomllib
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.session_controller import GameSessionController
from marvel_mcp_narrator.interfaces.cli import (
    _ACTIVE_SESSION_CONTROLLER,
    CLI_COMMANDS_HELP,
    DEFAULT_MODEL,
    STARTUP_MEMORY_LIMIT,
    STARTUP_CONTEXT_EMPTY_NOTE,
    STARTUP_CONTEXT_UNAVAILABLE_NOTE,
    DEFAULT_REQUEST_TIMEOUT,
    _parse_manual_roll_text,
    _route_intent_command,
    _tool_injection,
    get_combat_state,
    get_active_character_context,
    get_active_combat_context,
    get_rules_startup_context,
    build_startup_system_prompt,
    build_open_webui_chat_endpoint,
    get_startup_context,
    list_campaign_memories,
    load_cli_config,
    main,
    normalize_open_webui_host,
    request_open_webui_chat,
    run_cli,
)
from marvel_mcp_narrator.mcp_servers.narrator_tools import clear_combat_state


class CLIToolInjectionTests(unittest.TestCase):
    def setUp(self):
        clear_combat_state()

    def tearDown(self):
        clear_combat_state()

    def test_router_rules_command_returns_rule_text(self):
        name, payload = _route_intent_command('/rules edge')
        self.assertEqual(name, 'lookup_rule')
        self.assertIn('Rulebook Search Results', payload)

    def test_router_memories_command_lists_memories(self):
        with patch('marvel_mcp_narrator.interfaces.cli.list_campaign_memories', return_value=[
            {"key": "session-1", "content": "Hydra attacked.", "updated_at": "2026-09-21T10:00:00+00:00"}
        ]):
            name, payload = _route_intent_command('/memories')
        self.assertEqual(name, 'list_memories')
        self.assertIn('Campaign Memories:', payload)
        self.assertIn('Hydra attacked.', payload)

    def test_router_roll_command_supports_positional_edges_and_troubles(self):
        with patch('marvel_mcp_narrator.interfaces.cli.resolve_d616_roll', return_value={
            "dice_values": [3, 2, 5],
            "total_score": 10,
            "is_fantastic": False,
            "is_ultimate": False,
            "is_botch": False,
            "target_number": None,
        }) as mock_roll:
            name, payload = _route_intent_command('/roll 2 1')
        self.assertEqual(name, 'resolve_d616_roll')
        mock_roll.assert_called_once_with(ability_modifier=0, edges=2, troubles=1)
        self.assertIn('Deterministic d616 Roll:', payload)
        self.assertIn('Total Score: 10', payload)

    def test_parse_manual_roll_text_detects_marvel_marker(self):
        dice_values, marvel_index = _parse_manual_roll_text("[4, 5, 1 (Marvel)]")
        self.assertEqual(dice_values, [4, 5, 1])
        self.assertEqual(marvel_index, 2)

    def test_parse_manual_roll_text_rejects_non_die_bracket_content(self):
        with self.assertRaisesRegex(ValueError, "must be a die value"):
            _parse_manual_roll_text("[4 hp, 5 focus, 1]")

    def test_parse_manual_roll_text_requires_explicit_marvel_marker(self):
        with self.assertRaisesRegex(ValueError, "explicitly mark"):
            _parse_manual_roll_text("[4, 5, 1]")

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_manual_d616_roll', return_value={
        "dice_values": [4, 5, 1],
        "total_score": 15,
        "is_fantastic": True,
        "is_ultimate": False,
        "is_botch": False,
        "target_number": None,
    })
    def test_router_accepts_plain_manual_d616_report(self, mock_manual_roll):
        name, payload = _route_intent_command('[4, 5, 1 (Marvel)]')
        self.assertEqual(name, 'manual_d616_report')
        mock_manual_roll.assert_called_once_with(dice_values=[4, 5, 1], marvel_index=2)
        self.assertIn('Fantastic: True', payload)

    def test_router_does_not_treat_roll_plus_narration_as_standalone_manual_report(self):
        self.assertIsNone(_route_intent_command('[4, 5, 1 (Marvel)] Spider-Man lunges forward'))

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_player_attack', return_value={
        "attacker": {"name": "Spider-Man", "side": "player"},
        "target": {"name": "Hydra", "side": "enemy", "current_health": 71, "max_health": 75, "current_focus": 50, "max_focus": 50},
        "ability": "melee",
        "target_number": 13,
        "target_resource": "health",
        "roll": {"dice_values": [6, 1, 6], "total_score": 22, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 4},
    })
    def test_router_attack_command_accepts_manual_roll_suffix(self, mock_attack):
        name, payload = _route_intent_command('/attack Spider-Man melee Hydra [6, 1 (Marvel), 6]')
        self.assertEqual(name, 'resolve_player_attack')
        mock_attack.assert_called_once_with(
            attacker_name='Spider-Man',
            target_name='Hydra',
            ability='melee',
            dice_values=[6, 1, 6],
            marvel_index=1,
            target_resource='health',
            edges=0,
            troubles=0,
        )
        self.assertIn('Damage: 4 health', payload)

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_player_attack', return_value={
        "attacker": {"name": "Spider-Man", "side": "player"},
        "target": {"name": "Hydra", "side": "enemy", "current_health": 71, "max_health": 75, "current_focus": 32, "max_focus": 50},
        "ability": "melee",
        "target_number": 13,
        "target_resource": "focus",
        "roll": {"dice_values": [6, 1, 6], "total_score": 22, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 18},
    })
    def test_router_attack_command_preserves_flags_after_manual_roll(self, mock_attack):
        name, _payload = _route_intent_command(
            '/attack Spider-Man melee Hydra [6, 1 (Marvel), 6] --edges 2 --troubles 1 --focus'
        )
        self.assertEqual(name, 'resolve_player_attack')
        mock_attack.assert_called_once_with(
            attacker_name='Spider-Man',
            target_name='Hydra',
            ability='melee',
            dice_values=[6, 1, 6],
            marvel_index=1,
            target_resource='focus',
            edges=2,
            troubles=1,
        )

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_player_attack', return_value={
        "attacker": {"name": "Captain America", "side": "player"},
        "target": {"name": "Red Skull", "side": "enemy", "current_health": 71, "max_health": 75, "current_focus": 50, "max_focus": 50},
        "ability": "melee",
        "target_number": 13,
        "target_resource": "health",
        "roll": {"dice_values": [6, 1, 6], "total_score": 22, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 4},
    })
    def test_router_attack_command_supports_multi_word_names(self, mock_attack):
        name, _payload = _route_intent_command('/attack Captain America melee Red Skull')
        self.assertEqual(name, 'resolve_player_attack')
        mock_attack.assert_called_once_with(
            attacker_name='Captain America',
            target_name='Red Skull',
            ability='melee',
            dice_values=None,
            marvel_index=1,
            target_resource='health',
            edges=0,
            troubles=0,
        )

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_npc_action', return_value={
        "attacker": {"name": "Red Skull", "side": "enemy"},
        "target": {"name": "Captain America", "side": "player", "current_health": 75, "max_health": 100, "current_focus": 80, "max_focus": 100},
        "ability": "ego",
        "target_number": 15,
        "target_resource": "focus",
        "roll": {"dice_values": [6, 1, 5], "total_score": 18, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 18},
    })
    def test_router_npc_attack_passes_edges_troubles_and_focus_flags(self, mock_attack):
        name, _payload = _route_intent_command('/npc-attack Red Skull ego Captain America --edges 2 --troubles 1 --focus')
        self.assertEqual(name, 'resolve_npc_action')
        mock_attack.assert_called_once_with(
            attacker_name='Red Skull',
            target_name='Captain America',
            ability='ego',
            target_resource='focus',
            edges=2,
            troubles=1,
        )

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_player_attack', return_value={
        "attacker": {"name": "Spider-Man", "side": "player"},
        "target": {"name": "Hydra", "side": "enemy", "current_health": 71, "max_health": 75, "current_focus": 32, "max_focus": 50},
        "ability": "melee",
        "target_number": 13,
        "target_resource": "focus",
        "roll": {"dice_values": [6, 1, 6], "total_score": 22, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 18},
    })
    def test_router_attack_command_accepts_flags_before_names(self, mock_attack):
        name, _payload = _route_intent_command('/attack --focus Spider-Man --edges 2 melee Hydra')
        self.assertEqual(name, 'resolve_player_attack')
        mock_attack.assert_called_once_with(
            attacker_name='Spider-Man',
            target_name='Hydra',
            ability='melee',
            dice_values=None,
            marvel_index=1,
            target_resource='focus',
            edges=2,
            troubles=0,
        )

    @patch('marvel_mcp_narrator.interfaces.cli.get_combat_state', return_value={
        "combatants": [
            {"name": "Hydra", "side": "enemy", "current_health": 30, "max_health": 50, "current_focus": 20, "max_focus": 20}
        ]
    })
    def test_get_active_combat_context_formats_health_tracker(self, _mock_state):
        context = get_active_combat_context()
        self.assertIn('Active Combat State:', context)
        self.assertIn('Hydra', context)
        self.assertIn('30/50', context)

    def test_context_local_session_controller_isolates_cli_wrappers(self):
        with TemporaryDirectory() as temp_dir:
            db1 = CampaignDatabase(Path(temp_dir) / "campaign-1.db")
            db2 = CampaignDatabase(Path(temp_dir) / "campaign-2.db")
            controller1 = GameSessionController(campaign_database=db1)
            controller2 = GameSessionController(campaign_database=db2)

            character_roster.create_or_load(
                name="Hydra",
                archetype="Striker",
                rank=2,
                melee=4,
                agility=2,
                resilience=3,
                vigilance=2,
                ego=1,
                logic=1,
            )
            controller1.combat_tracker.track_combatant("Hydra", side="enemy")
            db1.save_memory("session-1", "Hydra attacked.")
            db2.save_memory("session-2", "Avengers regrouped.")

            token1 = _ACTIVE_SESSION_CONTROLLER.set(controller1)
            try:
                self.assertEqual(get_combat_state()["combatants"][0]["name"], "Hydra")
                self.assertEqual(list_campaign_memories()[0]["key"], "session-1")
            finally:
                _ACTIVE_SESSION_CONTROLLER.reset(token1)

            token2 = _ACTIVE_SESSION_CONTROLLER.set(controller2)
            try:
                self.assertEqual(get_combat_state()["combatants"], [])
                self.assertEqual(list_campaign_memories()[0]["key"], "session-2")
            finally:
                _ACTIVE_SESSION_CONTROLLER.reset(token2)

    def test_roll_command_returns_tool_payload(self):
        name, payload = _tool_injection('/roll --tn 10')
        self.assertEqual(name, 'roll_d616')
        self.assertIn('total', payload)
        self.assertEqual(payload['target_number'], 10)

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_d616_roll', return_value={
        "dice_values": [3, 2, 5],
        "total_score": 10,
        "is_fantastic": False,
        "is_ultimate": False,
        "is_botch": False,
        "target_number": 12,
        "success": False,
    })
    def test_roll_command_supports_counted_edge_and_trouble_flags(self, mock_roll):
        name, payload = _tool_injection('/roll --edges 2 --troubles 1 --tn 12')
        self.assertEqual(name, 'resolve_d616_roll')
        mock_roll.assert_called_once_with(ability_modifier=0, edges=2, troubles=1, target_number=12)
        self.assertEqual(payload['target_number'], 12)

    def test_rule_command_returns_search_results(self):
        name, payload = _tool_injection('/rule edge')
        self.assertEqual(name, 'lookup_rule')
        self.assertIn('Rulebook Search Results', payload)
        self.assertIn('Edges and Troubles', payload)

    def test_rule_command_returns_d616_rules(self):
        name, payload = _tool_injection('/rule d616')
        self.assertEqual(name, 'lookup_rule')
        self.assertIn('d616 Basics', payload)
        self.assertIn('d616 Roll Breakdown', payload)

    def test_rule_command_uses_exact_rule_index_when_key_matches(self):
        name, payload = _tool_injection('/rule d616_basics')
        self.assertEqual(name, 'lookup_rule')
        self.assertIn('Rule Reference: d616 Basics', payload)
        self.assertIn('`d616_basics`', payload)

    def test_rule_command_returns_not_found_for_unknown_rule(self):
        name, payload = _tool_injection('/rule not-a-real-rule')
        self.assertEqual(name, 'lookup_rule')
        self.assertEqual(payload, "Rule not found: 'not-a-real-rule'.")

    def test_roll_invalid_target_number_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn nope')

    def test_roll_rejects_unexpected_positional_argument(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll foo')

    def test_roll_rejects_extra_argument_after_target_number(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn 10 extra')

    def test_roll_rejects_flag_as_target_number_value(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn --edge')

    def test_roll_rejects_negative_target_number(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn -1')

    def test_roll_rejects_zero_target_number(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn 0')

    def test_roll_accepts_plus_prefixed_target_number(self):
        name, payload = _tool_injection('/roll --tn +10')
        self.assertEqual(name, 'roll_d616')
        self.assertEqual(payload['target_number'], 10)

    def test_roll_rejects_duplicate_flags(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --edge --edge')
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn 10 --tn 20')

    def test_roll_edge_trouble_combo_raises_configuration_error(self):
        with self.assertRaises(D616ConfigurationError):
            _tool_injection('/roll --edge --trouble')


class CLIRunLoopTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()
        clear_combat_state()

    def tearDown(self):
        character_roster.clear()
        clear_combat_state()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    @patch('marvel_mcp_narrator.interfaces.cli.get_startup_context', return_value='Campaign Memory Context:\n- session-1: Avengers assembled.')
    @patch('marvel_mcp_narrator.interfaces.cli.get_rules_startup_context', return_value='Core d616 Rules Context:\n- Damage Formula: Base Damage = Rank × Marvel Die')
    @patch('marvel_mcp_narrator.interfaces.cli.get_active_character_context', return_value='Active Character Context:\n- No active character is currently loaded.')
    def test_run_cli_injects_startup_memory_into_system_prompt(self, _mock_active, _mock_rules, _mock_context, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model')

        call_messages = mock_request_chat.call_args.kwargs['messages']
        self.assertEqual(call_messages[0]['role'], 'system')
        self.assertIn('Core d616 Rules Context:', call_messages[0]['content'])
        self.assertIn('Campaign Memory Context:', call_messages[0]['content'])
        self.assertIn('Avengers assembled.', call_messages[0]['content'])
        self.assertIn('Marvel Multiverse RPG narrator copilot', call_messages[0]['content'])

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=[' /HELP ', 'exit'])
    def test_help_command_does_not_call_chat_backend(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_shuts_down_gracefully(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=EOFError)
    def test_eof_shuts_down_gracefully(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_non_tool_message_is_sent_to_chat_api(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model')

        call_messages = mock_request_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == 'hello narrator' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_chat_response_is_handled(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'
        run_cli(model='fake-model')
        mock_request_chat.assert_called_once()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/roll', 'exit'])
    def test_roll_tool_bypasses_chat_backend(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/rules teleport', 'exit'])
    def test_rules_command_bypasses_chat_backend(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('marvel_mcp_narrator.interfaces.cli.list_campaign_memories', return_value=[
        {"key": "session-1", "content": "Hydra attacked.", "updated_at": "2026-09-21T10:00:00+00:00"}
    ])
    @patch('builtins.input', side_effect=['/memories', 'exit'])
    def test_memories_command_bypasses_chat_backend(self, _mock_input, _mock_memories, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.resolve_player_attack', return_value={
        "attacker": {"name": "Spider-Man", "side": "player"},
        "target": {"name": "Hydra", "side": "enemy", "current_health": 71, "max_health": 75, "current_focus": 50, "max_focus": 50},
        "ability": "melee",
        "target_number": 13,
        "target_resource": "health",
        "roll": {"dice_values": [6, 1, 6], "total_score": 22, "is_fantastic": True, "success": True},
        "damage": {"total_damage": 4},
    })
    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/attack Spider-Man melee Hydra [6, 1 (Marvel), 6]', 'exit'])
    def test_attack_command_bypasses_chat_backend(self, _mock_input, mock_request_chat, _mock_attack):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/rules teleport', 'hello narrator', 'exit'])
    def test_routed_command_is_injected_into_history_for_following_chat_turn(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model')

        call_messages = mock_request_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == '/rules teleport' for msg in call_messages))
        self.assertTrue(any(msg['role'] == 'tool' and 'Deterministic router output (lookup_rule):' in msg['content'] for msg in call_messages))
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == 'hello narrator' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['[4, 5, 1 (Marvel)]', 'hello narrator', 'exit'])
    def test_manual_roll_report_is_injected_into_history_for_following_chat_turn(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model')

        call_messages = mock_request_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == '[4, 5, 1 (Marvel)]' for msg in call_messages))
        self.assertTrue(
            any(msg['role'] == 'tool' and 'Deterministic router output (manual_d616_report):' in msg['content'] for msg in call_messages)
        )

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/roll --tn nope', 'exit'])
    def test_tool_error_does_not_call_chat_backend(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/rule', 'exit'])
    def test_rule_usage_error_does_not_call_chat_backend(self, _mock_input, mock_request_chat):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.query_rulebook_database', side_effect=OSError('rules missing'))
    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['/rule d616', 'exit'])
    def test_rule_loader_error_does_not_crash_loop(self, _mock_input, mock_request_chat, _mock_query):
        run_cli(model='fake-model')
        mock_request_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_transport_exception_does_not_crash_loop(self, _mock_input, mock_request_chat):
        mock_request_chat.side_effect = RuntimeError('Connection refused')
        run_cli(model='fake-model')
        mock_request_chat.assert_called_once()

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'hello narrator', 'exit'])
    def test_chat_error_rolls_back_pending_turn_messages(self, _mock_input, mock_request_chat):
        mock_request_chat.side_effect = [RuntimeError('stream dropped'), RuntimeError('stream dropped')]

        run_cli(model='fake-model')

        second_messages = mock_request_chat.call_args_list[1].kwargs['messages']
        user_turns = [msg for msg in second_messages if msg['role'] == 'user' and msg['content'] == 'hello narrator']
        self.assertEqual(len(user_turns), 1)
        self.assertFalse(any(msg['role'] == 'assistant' for msg in second_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_client_uses_configured_host_and_api_key(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model', host='http://remote:3000', api_key='secret-token')

        mock_request_chat.assert_called_once()
        kwargs = mock_request_chat.call_args.kwargs
        self.assertEqual(kwargs['host'], 'http://remote:3000')
        self.assertEqual(kwargs['api_key'], 'secret-token')
        self.assertEqual(kwargs['timeout'], DEFAULT_REQUEST_TIMEOUT)

    @patch('marvel_mcp_narrator.interfaces.cli.request_open_webui_chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_client_uses_configured_timeout(self, _mock_input, mock_request_chat):
        mock_request_chat.return_value = 'hi'

        run_cli(model='fake-model', timeout=45.5)

        kwargs = mock_request_chat.call_args.kwargs
        self.assertEqual(kwargs['timeout'], 45.5)


class CLIMainTests(unittest.TestCase):
    @patch.dict('os.environ', {}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli'])
    def test_main_uses_default_model(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(
            model=DEFAULT_MODEL,
            host='http://127.0.0.1:3000',
            base_url='http://127.0.0.1:3000',
            api_key=None,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli', '--model', 'qwen2.5-coder'])
    def test_main_passes_custom_model(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(
            model='qwen2.5-coder',
            host='http://127.0.0.1:3000',
            base_url='http://127.0.0.1:3000',
            api_key=None,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli', '--host', 'http://remote:11434', '--api-key', 'abc123'])
    def test_main_passes_custom_host_and_api_key(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(
            model=DEFAULT_MODEL,
            host='http://remote:11434',
            base_url='http://remote:11434',
            api_key='abc123',
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli', '--base-url', 'http://localhost:11434/v1'])
    def test_main_passes_custom_base_url(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(
            model=DEFAULT_MODEL,
            host='http://127.0.0.1:3000',
            base_url='http://localhost:11434/v1',
            api_key=None,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli', '--timeout', '30'])
    def test_main_passes_custom_timeout(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(
            model=DEFAULT_MODEL,
            host='http://127.0.0.1:3000',
            base_url='http://127.0.0.1:3000',
            api_key=None,
            timeout=30.0,
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('sys.argv', ['cli', '--help'])
    def test_main_help_includes_interactive_commands(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc:
                main()
        self.assertEqual(exc.exception.code, 0)
        help_output = stdout.getvalue()
        self.assertIn("Interactive commands:", help_output)
        self.assertIn("/help", help_output)
        self.assertIn("Ctrl+C", help_output)

    def test_cli_help_epilog_mentions_shutdown_commands(self):
        self.assertIn("/help", CLI_COMMANDS_HELP)
        self.assertIn("Ctrl+C", CLI_COMMANDS_HELP)
        self.assertIn("/exit", CLI_COMMANDS_HELP)


class CLIHostNormalizationTests(unittest.TestCase):
    def test_normalize_open_webui_host_keeps_base_host_when_missing_path(self):
        self.assertEqual(
            normalize_open_webui_host('http://localhost:3000'),
            'http://localhost:3000',
        )

    def test_normalize_open_webui_host_strips_chat_endpoint_suffix(self):
        self.assertEqual(
            normalize_open_webui_host('http://localhost:3000/api/chat/completions'),
            'http://localhost:3000',
        )

    def test_normalize_open_webui_host_keeps_other_paths(self):
        self.assertEqual(
            normalize_open_webui_host('http://localhost:3000/openwebui'),
            'http://localhost:3000/openwebui',
        )

    def test_build_open_webui_chat_endpoint_appends_api_path(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:3000'),
            'http://localhost:3000/api/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_openai_path_for_v1(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/v1'),
            'http://localhost:11434/v1/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_openai_path_for_nested_v1(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/openai/v1'),
            'http://localhost:11434/openai/v1/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_openai_path_for_api_v1(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/api/v1'),
            'http://localhost:11434/api/v1/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_openai_path_for_v2(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/v2'),
            'http://localhost:11434/v2/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_openai_path_for_openai_base(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/openai'),
            'http://localhost:11434/openai/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_appends_completions_for_chat_base(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/v1/chat'),
            'http://localhost:11434/v1/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_rewrites_completions_path_to_chat(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/v1/completions'),
            'http://localhost:11434/v1/chat/completions',
        )

    def test_build_open_webui_chat_endpoint_preserves_query_params(self):
        self.assertEqual(
            build_open_webui_chat_endpoint('http://localhost:11434/v1?api-version=2024-12-01'),
            'http://localhost:11434/v1/chat/completions?api-version=2024-12-01',
        )


class CLIConfigTests(unittest.TestCase):
    def test_load_cli_config_reads_file_values(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[open_webui]\n'
                'model = "qwen2.5-coder"\n'
                'host = "http://remote:11434"\n'
                'base_url = "http://remote:11434/v1"\n'
                'api_key = "key-from-file"\n',
                encoding='utf-8',
            )
            config = load_cli_config(str(config_path))

        self.assertEqual(config['model'], 'qwen2.5-coder')
        self.assertEqual(config['host'], 'http://remote:11434')
        self.assertEqual(config['base_url'], 'http://remote:11434/v1')
        self.assertEqual(config['api_key'], 'key-from-file')
        self.assertEqual(config['timeout'], DEFAULT_REQUEST_TIMEOUT)

    def test_load_cli_config_reads_timeout_from_file(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[open_webui]\n'
                'timeout = 45.5\n',
                encoding='utf-8',
            )
            config = load_cli_config(str(config_path))

        self.assertEqual(config['timeout'], 45.5)

    def test_load_cli_config_accepts_legacy_ollama_file_block(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[ollama]\n'
                'model = "legacy-model"\n'
                'host = "http://legacy-host:11434"\n'
                'api_key = "legacy-key"\n',
                encoding='utf-8',
            )
            config = load_cli_config(str(config_path))

        self.assertEqual(config['model'], 'legacy-model')
        self.assertEqual(config['host'], 'http://legacy-host:11434')
        self.assertEqual(config['api_key'], 'legacy-key')

    @patch.dict(
        'os.environ',
        {
            'NARRATOR_MODEL': 'env-model',
            'NARRATOR_OPEN_WEBUI_HOST': 'http://env-host:11434',
            'NARRATOR_API_KEY': 'env-key',
            'NARRATOR_TIMEOUT': '33',
        },
        clear=True,
    )
    def test_load_cli_config_env_overrides_file(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[open_webui]\n'
                'model = "file-model"\n'
                'host = "http://file-host:11434"\n'
                'api_key = "file-key"\n',
                encoding='utf-8',
            )
            config = load_cli_config(str(config_path))

        self.assertEqual(config['model'], 'env-model')
        self.assertEqual(config['host'], 'http://env-host:11434')
        self.assertEqual(config['base_url'], 'http://env-host:11434')
        self.assertEqual(config['api_key'], 'env-key')
        self.assertEqual(config['timeout'], 33.0)

    @patch.dict(
        'os.environ',
        {
            'NARRATOR_OLLAMA_HOST': 'http://legacy-env-host:11434',
        },
        clear=True,
    )
    def test_load_cli_config_accepts_legacy_ollama_env_var(self):
        config = load_cli_config()

        self.assertEqual(config['host'], 'http://legacy-env-host:11434')
        self.assertEqual(config['base_url'], 'http://legacy-env-host:11434')

    @patch.dict(
        'os.environ',
        {
            'NARRATOR_OPEN_WEBUI_HOST': 'http://env-host:11434',
        },
        clear=True,
    )
    def test_load_cli_config_host_env_override_preserves_explicit_file_base_url(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[open_webui]\n'
                'host = "http://file-host:3000"\n'
                'base_url = "http://file-host:11434/v1"\n',
                encoding='utf-8',
            )
            config = load_cli_config(str(config_path))

        self.assertEqual(config['host'], 'http://env-host:11434')
        self.assertEqual(config['base_url'], 'http://file-host:11434/v1')

    @patch.dict(
        'os.environ',
        {
            'NARRATOR_OPENAI_BASE_URL': 'http://openai-host:11434/v1',
        },
        clear=True,
    )
    def test_load_cli_config_accepts_openai_base_url_env_var(self):
        config = load_cli_config()
        self.assertEqual(config['base_url'], 'http://openai-host:11434/v1')

    def test_load_cli_config_rejects_invalid_timeout_in_file(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'narrator_config.toml'
            config_path.write_text(
                '[open_webui]\n'
                'timeout = 0\n',
                encoding='utf-8',
            )
            with self.assertRaisesRegex(ValueError, 'Timeout must be a positive number'):
                load_cli_config(str(config_path))

    @patch.dict('os.environ', {'NARRATOR_TIMEOUT': 'oops'}, clear=True)
    def test_load_cli_config_rejects_invalid_timeout_env_var(self):
        with self.assertRaisesRegex(ValueError, 'Timeout must be a positive number'):
            load_cli_config()


class OpenWebUIRequestTests(unittest.TestCase):
    @patch('marvel_mcp_narrator.interfaces.cli.httpx.post')
    def test_request_open_webui_chat_calls_chat_completions_endpoint(self, mock_post):
        mock_post.return_value.json.return_value = {
            'choices': [{'message': {'content': 'hello'}}],
        }
        response = request_open_webui_chat(
            host='http://localhost:3000',
            model=DEFAULT_MODEL,
            messages=[{'role': 'user', 'content': 'hi'}],
            api_key='token',
        )
        self.assertEqual(response, 'hello')
        kwargs = mock_post.call_args.kwargs
        self.assertTrue(kwargs['headers']['Authorization'].endswith('token'))
        self.assertEqual(kwargs['json']['stream'], False)
        self.assertEqual(
            mock_post.call_args.args[0],
            'http://localhost:3000/api/chat/completions',
        )
        self.assertEqual(kwargs['timeout'], DEFAULT_REQUEST_TIMEOUT)

    @patch('marvel_mcp_narrator.interfaces.cli.httpx.post')
    def test_request_open_webui_chat_accepts_custom_timeout(self, mock_post):
        mock_post.return_value.json.return_value = {
            'choices': [{'message': {'content': 'hello'}}],
        }
        request_open_webui_chat(
            host='http://localhost:3000',
            model=DEFAULT_MODEL,
            messages=[{'role': 'user', 'content': 'hi'}],
            timeout=22.25,
        )
        self.assertEqual(mock_post.call_args.kwargs['timeout'], 22.25)

    @patch('marvel_mcp_narrator.interfaces.cli.httpx.post')
    def test_request_open_webui_chat_supports_openai_compatible_base_url(self, mock_post):
        mock_post.return_value.json.return_value = {
            'choices': [{'message': {'content': 'hello'}}],
        }
        request_open_webui_chat(
            base_url='http://localhost:11434/v1',
            model=DEFAULT_MODEL,
            messages=[{'role': 'user', 'content': 'hi'}],
        )
        self.assertEqual(
            mock_post.call_args.args[0],
            'http://localhost:11434/v1/chat/completions',
        )

    @patch.dict('os.environ', {'NARRATOR_OPENAI_BASE_URL': 'http://localhost:11434/v1'}, clear=True)
    @patch('marvel_mcp_narrator.interfaces.cli.httpx.post')
    def test_openai_base_url_env_routes_to_v1_chat_completions(self, mock_post):
        mock_post.return_value.json.return_value = {
            'choices': [{'message': {'content': 'hello'}}],
        }
        config = load_cli_config()
        request_open_webui_chat(
            base_url=config['base_url'],
            model=DEFAULT_MODEL,
            messages=[{'role': 'user', 'content': 'hi'}],
        )
        self.assertEqual(
            mock_post.call_args.args[0],
            'http://localhost:11434/v1/chat/completions',
        )


class CLIStartupContextTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()

    def tearDown(self):
        character_roster.clear()

    def test_get_rules_startup_context_includes_core_math_rules(self):
        context = get_rules_startup_context()

        self.assertIn("Core d616 Rules Context:", context)
        self.assertIn("Health = Resilience × 25", context)
        self.assertIn("Focus = Vigilance × 25", context)
        self.assertIn("Base Damage = Rank × Marvel Die", context)

    def test_get_active_character_context_uses_current_tracked_character(self):
        character_roster.create_or_load(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=5,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )

        context = get_active_character_context()

        self.assertIn("Storm", context)
        self.assertIn("Health 75", context)
        self.assertIn("Focus 125", context)
        self.assertIn("Running Speed 6 spaces", context)
        self.assertIn("Base damage = Rank 4 × Marvel Die", context)

    def test_get_startup_context_uses_fresh_campaign_note_when_memory_is_empty(self):
        class EmptyDatabase:
            def list_memories(self):
                return []

        context = get_startup_context(EmptyDatabase())

        self.assertIn("Campaign Memory Context:", context)
        self.assertIn(STARTUP_CONTEXT_EMPTY_NOTE, context)

    def test_get_startup_context_formats_saved_memories(self):
        class MemoryDatabase:
            def list_memories(self):
                return [
                    {
                        "key": "session-2",
                        "content": "Doctor Doom escaped with the artifact.",
                        "updated_at": "2026-09-21T09:00:00+00:00",
                    },
                    {
                        "key": "session-1",
                        "content": "The Fantastic Four reached Latveria.",
                        "updated_at": "2026-09-20T09:00:00+00:00",
                    },
                ]

        context = get_startup_context(MemoryDatabase())

        self.assertIn("[2026-09-21T09:00:00+00:00] session-2: Doctor Doom escaped with the artifact.", context)
        self.assertIn("[2026-09-20T09:00:00+00:00] session-1: The Fantastic Four reached Latveria.", context)

    def test_get_startup_context_limits_injected_memories(self):
        class MemoryDatabase:
            def list_memories(self):
                return [
                    {
                        "key": f"session-{index}",
                        "content": f"Event {index}",
                        "updated_at": "2026-09-21T09:00:00+00:00",
                    }
                    for index in range(STARTUP_MEMORY_LIMIT + 3)
                ]

        context = get_startup_context(MemoryDatabase())

        self.assertIn("Additional memories omitted", context)
        self.assertIn(f"({3} more)", context)
        self.assertNotIn(f"session-{STARTUP_MEMORY_LIMIT + 2}", context)

    def test_get_startup_context_omission_count_includes_budget_and_limit_overflow(self):
        class MemoryDatabase:
            def list_memories(self):
                return [
                    {
                        "key": f"session-{index}",
                        "content": "A" * 80,
                        "updated_at": "2026-09-21T09:00:00+00:00",
                    }
                    for index in range(STARTUP_MEMORY_LIMIT + 4)
                ]

        with patch('marvel_mcp_narrator.interfaces.cli.STARTUP_CONTEXT_CHAR_BUDGET', 120):
            context = get_startup_context(MemoryDatabase())

        self.assertIn("Additional memories omitted", context)
        self.assertIn(f"({STARTUP_MEMORY_LIMIT + 4} more)", context)
        self.assertLessEqual(len(context), 120)

    def test_get_startup_context_remains_informative_when_budget_is_tiny(self):
        class MemoryDatabase:
            def list_memories(self):
                return [
                    {
                        "key": "session-1",
                        "content": "A" * 200,
                        "updated_at": "2026-09-21T09:00:00+00:00",
                    }
                ]

        with patch('marvel_mcp_narrator.interfaces.cli.STARTUP_CONTEXT_CHAR_BUDGET', 40):
            context = get_startup_context(MemoryDatabase())

        self.assertTrue(context.startswith("Campaign Memory Context:"))
        self.assertGreater(len(context.splitlines()), 1)
        self.assertIn("+1", context)
        self.assertLessEqual(len(context), 40)

    def test_get_startup_context_handles_database_errors_gracefully(self):
        class BrokenDatabase:
            def list_memories(self):
                raise OSError("database unavailable")

        context = get_startup_context(BrokenDatabase())

        self.assertIn(STARTUP_CONTEXT_UNAVAILABLE_NOTE, context)

    def test_get_startup_context_respects_budget_smaller_than_header(self):
        class EmptyDatabase:
            def list_memories(self):
                return []

        with patch('marvel_mcp_narrator.interfaces.cli.STARTUP_CONTEXT_CHAR_BUDGET', 5):
            context = get_startup_context(EmptyDatabase())

        self.assertLessEqual(len(context), 5)

    def test_build_startup_system_prompt_prepends_memory_context(self):
        class MemoryDatabase:
            def list_memories(self):
                return [{"key": "session-1", "content": "Hydra infiltrated the Helicarrier.", "updated_at": ""}]

        prompt = build_startup_system_prompt(MemoryDatabase())

        self.assertTrue(prompt.startswith("You are a Marvel Multiverse RPG narrator copilot."))
        self.assertIn("Core d616 Rules Context:", prompt)
        self.assertIn("Active Character Context:", prompt)
        self.assertIn("Campaign Memory Context:", prompt)
        self.assertIn("Hydra infiltrated the Helicarrier.", prompt)
        self.assertIn("Marvel Multiverse RPG narrator copilot", prompt)


class PackagingEntryPointTests(unittest.TestCase):
    def test_pyproject_defines_cli_entrypoint(self):
        pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
        data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
        self.assertEqual(
            data['project']['scripts']['marvel-narrator-cli'],
            'marvel_mcp_narrator.interfaces.cli:main',
        )

    def test_root_requirements_file_exists(self):
        requirements = Path(__file__).resolve().parent.parent / 'requirements.txt'
        self.assertTrue(requirements.is_file())


if __name__ == '__main__':
    unittest.main()
