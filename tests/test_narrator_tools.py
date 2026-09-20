import unittest

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.mcp_servers import narrator_tools


class NarratorToolsTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()

    def tearDown(self):
        character_roster.clear()

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
        self.assertEqual(payload["max_focus"], 150)

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
        self.assertEqual(payload["health"]["current"], 105)
        self.assertEqual(payload["focus"]["current"], 50)

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
        self.assertEqual(payload["base_damage"], 29)
        self.assertEqual(payload["total_damage"], 58)

    def test_new_character_tools_are_callable(self):
        self.assertTrue(callable(narrator_tools.create_character))
        self.assertTrue(callable(narrator_tools.get_character))
        self.assertTrue(callable(narrator_tools.apply_damage_to_character))
        self.assertTrue(callable(narrator_tools.calculate_attack))


if __name__ == "__main__":
    unittest.main()
