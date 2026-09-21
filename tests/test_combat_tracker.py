import unittest
from unittest.mock import patch

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.combat_tracker import CombatTracker


class CombatTrackerTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()
        self.tracker = CombatTracker()

    def tearDown(self):
        character_roster.clear()
        self.tracker.clear()

    def test_track_combatant_returns_health_snapshot(self):
        character_roster.create_or_load(
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

        payload = self.tracker.track_combatant("Storm", side="player")

        self.assertEqual(payload["name"], "Storm")
        self.assertEqual(payload["side"], "player")
        self.assertEqual(payload["max_health"], 75)
        self.assertEqual(payload["current_health"], 75)

    def test_resolve_manual_roll_uses_effective_marvel_value(self):
        payload = self.tracker.resolve_manual_roll(
            dice_values=[4, 5, 1],
            marvel_index=2,
            ability_modifier=3,
            target_number=15,
        )

        self.assertEqual(payload["dice_values"], [4, 1, 5])
        self.assertEqual(payload["total_score"], 18)
        self.assertTrue(payload["is_fantastic"])
        self.assertTrue(payload["success"])

    @patch("marvel_mcp_narrator.core.combat_tracker.resolve_d616_roll")
    def test_resolve_npc_action_auto_applies_health_damage(self, mock_roll):
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
        character_roster.create_or_load(
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

        payload = self.tracker.resolve_npc_action(attacker_name="Hydra", target_name="Storm", ability="melee")

        self.assertEqual(payload["damage"]["total_damage"], 10)
        self.assertEqual(payload["target"]["current_health"], 65)
        self.assertEqual(payload["attacker"]["side"], "enemy")
        self.assertEqual(payload["target"]["side"], "player")


if __name__ == "__main__":
    unittest.main()
