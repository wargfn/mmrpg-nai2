import unittest
from unittest.mock import patch

from marvel_mcp_narrator.core.d616_engine import resolve_d616_roll, roll_d616


class FixedRng:
    def __init__(self, values):
        self._values = iter(values)

    def randint(self, _a, _b):
        return next(self._values)


class D616EngineTests(unittest.TestCase):
    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[2, 3, 1, 6])
    def test_resolve_d616_roll_supports_optional_params(self, _mock_roll):
        result = resolve_d616_roll(ability_modifier=3, target_number=14, edges=1)
        self.assertEqual(result["ability_modifier"], 3)
        self.assertEqual(result["target_number"], 14)
        self.assertEqual(result["net_modifiers"], 1)
        self.assertTrue(result["success"])

    def test_trouble_keeps_worse_marvel_die_when_other_is_one(self):
        # initial marvel=6, trouble die=1, regular dice=2,3
        result = roll_d616(trouble=True, rng=FixedRng([6, 1, 2, 3]))
        self.assertEqual(result['marvel_die'], 6)
        self.assertFalse(result['fantastic'])
        self.assertEqual(result['total'], 11)

    def test_edge_does_not_reroll_when_initial_marvel_die_is_one(self):
        # initial marvel=1, regular dice=2,3
        result = roll_d616(edge=True, rng=FixedRng([1, 2, 3]))
        self.assertEqual(result['marvel_die'], 1)
        self.assertEqual(result['marvel_rolls'], [1])
        self.assertTrue(result['fantastic'])
        self.assertEqual(result['total'], 12)

    def test_edge_rerolls_when_initial_marvel_die_is_not_one(self):
        # initial marvel=3, edge die=6, regular dice=2,3
        result = roll_d616(edge=True, rng=FixedRng([3, 6, 2, 3]))
        self.assertEqual(result['marvel_die'], 6)
        self.assertEqual(result['marvel_rolls'], [3, 6])
        self.assertFalse(result['fantastic'])
        self.assertEqual(result['total'], 11)

    def test_edge_prefers_rerolled_one_as_best_result(self):
        # initial marvel=6, edge die=1, regular dice=2,3
        result = roll_d616(edge=True, rng=FixedRng([6, 1, 2, 3]))
        self.assertEqual(result['marvel_die'], 1)
        self.assertEqual(result['marvel_rolls'], [6, 1])
        self.assertTrue(result['fantastic'])
        self.assertEqual(result['total'], 12)


if __name__ == '__main__':
    unittest.main()
