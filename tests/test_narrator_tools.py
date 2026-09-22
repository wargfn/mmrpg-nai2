import contextlib
import io
import unittest
from unittest.mock import patch

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.mcp_servers import narrator_tools


class NarratorToolsTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()
        narrator_tools.clear_combat_state()

    def tearDown(self):
        character_roster.clear()
        narrator_tools.clear_combat_state()

    def test_roll_d616_tool_uses_public_name(self):
        self.assertTrue(callable(narrator_tools.roll_d616))

    def test_lookup_rule_returns_exact_rule_reference_payload(self):
        payload = narrator_tools.lookup_rule("d616_basics")
        self.assertEqual(payload["rule_key"], "d616_basics")
        self.assertEqual(payload["entry_type"], "mechanic")

    def test_create_character_creates_sheet(self):
        payload = narrator_tools.create_character(
            name="Spider-Man",
            archetype="Polymath",
            rank=4,
            melee=5,
            agility=6,
            resilience=4,
            vigilance=5,
            ego=4,
            logic=4,
        )
        self.assertTrue(payload["created"])
        self.assertEqual(payload["character"]["name"], "Spider-Man")
        self.assertEqual(payload["character"]["defenses"]["agility_defense"], 16)

    def test_get_character_returns_existing_character_sheet(self):
        narrator_tools.create_character(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )
        payload = narrator_tools.get_character("Storm")
        self.assertEqual(payload["name"], "Storm")
        self.assertEqual(payload["max_focus"], 125)

    def test_get_character_accepts_trimmed_identifier(self):
        narrator_tools.create_character(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )
        payload = narrator_tools.get_character("  Storm  ")
        self.assertEqual(payload["name"], "Storm")

    def test_apply_damage_to_character_updates_resources(self):
        narrator_tools.create_character(
            name="Wolverine",
            archetype="Striker",
            rank=4,
            melee=5,
            agility=3,
            resilience=4,
            vigilance=2,
            ego=2,
            logic=2,
        )
        payload = narrator_tools.apply_damage_to_character("Wolverine", health_damage=15, focus_damage=10)
        self.assertEqual(payload["health"]["current"], 85)
        self.assertEqual(payload["focus"]["current"], 40)

    def test_calculate_attack_uses_character_rank_multiplier(self):
        narrator_tools.create_character(
            name="Captain Marvel",
            archetype="Blaster",
            rank=4,
            melee=3,
            agility=3,
            resilience=4,
            vigilance=4,
            ego=5,
            logic=3,
        )
        payload = narrator_tools.calculate_attack(
            attacker_name="Captain Marvel",
            ability="ego",
            marvel_die=6,
            is_fantastic=True,
        )
        self.assertEqual(payload["damage_multiplier"], 4)
        self.assertEqual(payload["base_damage"], 24)
        self.assertEqual(payload["total_damage"], 24)

    def test_new_character_tools_are_callable(self):
        self.assertTrue(callable(narrator_tools.create_character))
        self.assertTrue(callable(narrator_tools.get_character))
        self.assertTrue(callable(narrator_tools.apply_damage_to_character))
        self.assertTrue(callable(narrator_tools.calculate_attack))
        self.assertTrue(callable(narrator_tools.track_combatant))
        self.assertTrue(callable(narrator_tools.get_combat_state))
        self.assertTrue(callable(narrator_tools.resolve_manual_d616_roll))
        self.assertTrue(callable(narrator_tools.resolve_player_attack))
        self.assertTrue(callable(narrator_tools.resolve_npc_action))
        self.assertTrue(callable(narrator_tools.create_character_assisted))
        self.assertTrue(callable(narrator_tools.list_available_archetypes))
        self.assertTrue(callable(narrator_tools.list_available_origins))
        self.assertTrue(callable(narrator_tools.list_available_occupations))
        self.assertTrue(callable(narrator_tools.list_available_tags))
        self.assertTrue(callable(narrator_tools.export_character))
        self.assertTrue(callable(narrator_tools.validate_character_powers))

    def test_main_help_includes_fastmcp_startup_guidance(self):
        stdout = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(stdout):
            narrator_tools.main(["--help"])
        help_output = stdout.getvalue()
        self.assertIn("Start the Marvel MCP Narrator FastMCP server.", help_output)
        self.assertIn("--list-tools", help_output)
        self.assertIn("python -m marvel_mcp_narrator.mcp_servers.narrator_tools", help_output)

    def test_list_tools_command_prints_available_tools(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            narrator_tools.main(["--list-tools"])
        output = stdout.getvalue()
        self.assertIn("Available FastMCP narrator tools:", output)
        self.assertIn("roll_d616", output)
        self.assertIn("create_campaign_plan", output)

    @patch("marvel_mcp_narrator.mcp_servers.narrator_tools.mcp.run")
    def test_main_without_flags_starts_fastmcp_server(self, mock_run):
        narrator_tools.main([])
        mock_run.assert_called_once_with()

    def test_create_character_rejects_conflicting_definition(self):
        narrator_tools.create_character(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )
        with self.assertRaisesRegex(ValueError, "conflicting attributes"):
            narrator_tools.create_character(
                name="Storm",
                archetype="Blaster",
                rank=5,
                melee=2,
                agility=4,
                resilience=3,
                vigilance=5,
                ego=5,
                logic=3,
            )

    def test_create_character_rejects_blank_name(self):
        with self.assertRaisesRegex(ValueError, "name is required"):
            narrator_tools.create_character(
                name="   ",
                archetype="Blaster",
                rank=4,
                melee=2,
                agility=4,
                resilience=3,
                vigilance=5,
                ego=5,
                logic=3,
            )

    def test_resolve_manual_d616_roll_normalizes_manual_results(self):
        payload = narrator_tools.resolve_manual_d616_roll(
            dice_values=[4, 5, 1],
            marvel_index=2,
            ability_modifier=3,
            target_number=15,
        )
        self.assertEqual(payload["raw_dice"]["marvel_die"], 1)
        self.assertTrue(payload["is_fantastic"])
        self.assertEqual(payload["total_score"], 18)
        self.assertTrue(payload["success"])

    def test_track_combatant_and_get_combat_state(self):
        narrator_tools.create_character(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )
        tracked = narrator_tools.track_combatant("Storm", side="player")
        self.assertEqual(tracked["side"], "player")

        payload = narrator_tools.get_combat_state()
        self.assertEqual(len(payload["combatants"]), 1)
        self.assertEqual(payload["combatants"][0]["name"], "Storm")

    @patch("marvel_mcp_narrator.core.combat_tracker.resolve_d616_roll")
    def test_resolve_npc_action_auto_rolls_and_applies_damage(self, mock_roll):
        narrator_tools.create_character(
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
        narrator_tools.create_character(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )
        mock_roll.return_value = {
            "raw_dice": {"standard_1": 6, "marvel_die": 5, "standard_2": 4},
            "dice_values": [6, 5, 4],
            "total_score": 19,
            "is_fantastic": False,
            "is_ultimate": False,
            "is_botch": False,
            "target_number": 12,
            "success": True,
        }

        payload = narrator_tools.resolve_npc_action("Hydra", "Storm", "melee")

        self.assertEqual(payload["damage"]["total_damage"], 10)
        self.assertEqual(payload["target"]["current_health"], 65)
        self.assertEqual(payload["attacker"]["side"], "enemy")
        self.assertEqual(payload["target"]["side"], "player")

    def test_resolve_player_attack_accepts_manual_roll_and_updates_enemy_health(self):
        narrator_tools.create_character(
            name="Spider-Man",
            archetype="Polymath",
            rank=4,
            melee=5,
            agility=6,
            resilience=4,
            vigilance=5,
            ego=4,
            logic=4,
        )
        narrator_tools.create_character(
            name="Hydra",
            archetype="Striker",
            rank=2,
            melee=3,
            agility=2,
            resilience=3,
            vigilance=2,
            ego=1,
            logic=1,
        )

        payload = narrator_tools.resolve_player_attack(
            attacker_name="Spider-Man",
            target_name="Hydra",
            ability="melee",
            dice_values=[6, 1, 6],
            marvel_index=1,
        )

        self.assertTrue(payload["roll"]["success"])
        self.assertEqual(payload["damage"]["effective_marvel_die"], 6)
        self.assertEqual(payload["damage"]["total_damage"], 24)
        self.assertEqual(payload["target"]["current_health"], 51)


if __name__ == "__main__":
    unittest.main()
