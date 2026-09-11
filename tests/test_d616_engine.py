import unittest
from unittest.mock import patch

from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError, resolve_d616_roll, roll_d616


class FixedRng:
    def __init__(self, values):
        self._values = iter(values)

    def randint(self, _a, _b):
        return next(self._values)


class D616EngineTests(unittest.TestCase):
    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[2, 6, 3, 1])
    def test_resolve_d616_roll_supports_optional_params(self, _mock_roll):
        result = resolve_d616_roll(ability_modifier=3, target_number=14, edges=1)
        self.assertEqual(result["ability_modifier"], 3)
        self.assertEqual(result["target_number"], 14)
        self.assertEqual(result["net_modifiers"], 1)
        self.assertEqual(result["raw_dice"], {"standard_1": 2, "marvel_die": 1, "standard_2": 3})
        self.assertEqual(result["dice_values"], [2, 1, 3])
        self.assertEqual(result["total_score"], 14)
        self.assertTrue(result["is_fantastic"])
        self.assertTrue(result["success"])

    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[2, 1, 3, 6, 5])
    def test_resolve_d616_roll_edges_shift_to_standard_dice_after_marvel_success(self, _mock_roll):
        result = resolve_d616_roll(edges=2)
        self.assertEqual(result["raw_dice"], {"standard_1": 6, "marvel_die": 1, "standard_2": 5})
        self.assertEqual(result["dice_values"], [6, 1, 5])
        self.assertEqual(
            result["roll_history"],
            {"standard_1": [2, 6], "marvel_die": [1], "standard_2": [3, 5]},
        )
        self.assertEqual(result["total_score"], 17)

    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[4, 1, 6, 4, 2])
    def test_resolve_d616_roll_trouble_targets_marvel_then_high_standard(self, _mock_roll):
        result = resolve_d616_roll(troubles=2)
        self.assertEqual(result["raw_dice"], {"standard_1": 4, "marvel_die": 4, "standard_2": 2})
        self.assertEqual(result["dice_values"], [4, 4, 2])
        self.assertEqual(
            result["roll_history"],
            {"standard_1": [4], "marvel_die": [1, 4], "standard_2": [6, 2]},
        )
        self.assertEqual(result["total_score"], 10)
        self.assertFalse(result["is_fantastic"])

    def test_resolve_d616_roll_rejects_non_positive_target_number(self):
        with self.assertRaisesRegex(D616ConfigurationError, "positive integer"):
            resolve_d616_roll(target_number=0)

    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[1, 1, 1])
    def test_resolve_d616_roll_botch_overrides_success(self, _mock_roll):
        result = resolve_d616_roll(target_number=1)
        self.assertTrue(result["is_botch"])
        self.assertFalse(result["is_fantastic"])
        self.assertEqual(result["total_score"], 8)
        self.assertFalse(result["success"])

    @patch("marvel_mcp_narrator.core.d616_engine.roll_single_die", side_effect=[6, 1, 6])
    def test_resolve_d616_roll_ultimate_succeeds_even_with_high_target(self, _mock_roll):
        result = resolve_d616_roll(target_number=99)
        self.assertTrue(result["is_ultimate"])
        self.assertTrue(result["is_fantastic"])
        self.assertEqual(result["dice_values"], [6, 1, 6])
        self.assertEqual(result["total_score"], 18)
        self.assertTrue(result["success"])

    def test_roll_d616_rejects_non_positive_target_number(self):
        with self.assertRaisesRegex(D616ConfigurationError, "positive integer"):
            roll_d616(target_number=0, rng=FixedRng([1, 1, 1]))

    def test_roll_d616_botch_exposes_flag(self):
        result = roll_d616(target_number=5, rng=FixedRng([1, 1, 1]))
        self.assertEqual(result["raw_dice"], {"standard_1": 1, "marvel_die": 1, "standard_2": 1})
        self.assertTrue(result["botch"])
        self.assertFalse(result["fantastic"])
        self.assertEqual(result["total"], 8)
        self.assertFalse(result["success"])

    def test_roll_d616_ultimate_exposes_flag(self):
        result = roll_d616(target_number=99, rng=FixedRng([6, 1, 6]))
        self.assertTrue(result["ultimate"])
        self.assertTrue(result["fantastic"])
        self.assertEqual(result["dice_values"], [6, 1, 6])
        self.assertEqual(result["total"], 18)
        self.assertTrue(result["success"])

    def test_roll_d616_edge_keeps_marvel_first_priority(self):
        result = roll_d616(edge=True, rng=FixedRng([2, 4, 3, 1]))
        self.assertEqual(result["raw_dice"], {"standard_1": 2, "marvel_die": 1, "standard_2": 3})
        self.assertEqual(result["marvel_rolls"], [4, 1])
        self.assertTrue(result["fantastic"])
        self.assertEqual(result["total"], 11)

    def test_roll_d616_edge_uses_standard_die_when_marvel_is_already_one(self):
        result = roll_d616(edge=True, rng=FixedRng([2, 1, 3, 5]))
        self.assertEqual(result["raw_dice"], {"standard_1": 5, "marvel_die": 1, "standard_2": 3})
        self.assertEqual(result["marvel_rolls"], [1])
        self.assertEqual(result["standard_rolls"], {"standard_1": [2, 5], "standard_2": [3]})
        self.assertTrue(result["fantastic"])
        self.assertEqual(result["total"], 14)

    def test_roll_d616_trouble_knocks_marvel_off_one_first(self):
        result = roll_d616(trouble=True, rng=FixedRng([2, 1, 3, 6]))
        self.assertEqual(result["raw_dice"], {"standard_1": 2, "marvel_die": 6, "standard_2": 3})
        self.assertEqual(result["marvel_rolls"], [1, 6])
        self.assertFalse(result["fantastic"])
        self.assertEqual(result["total"], 11)

    def test_roll_d616_trouble_targets_high_standard_when_marvel_is_not_one(self):
        result = roll_d616(trouble=True, rng=FixedRng([2, 4, 6, 1]))
        self.assertEqual(result["raw_dice"], {"standard_1": 2, "marvel_die": 4, "standard_2": 1})
        self.assertEqual(result["marvel_rolls"], [4])
        self.assertEqual(result["standard_rolls"], {"standard_1": [2], "standard_2": [6, 1]})
        self.assertFalse(result["fantastic"])
        self.assertEqual(result["total"], 7)

    def test_roll_d616_rejects_simultaneous_edge_and_trouble(self):
        with self.assertRaisesRegex(D616ConfigurationError, "cannot both be active"):
            roll_d616(edge=True, trouble=True, rng=FixedRng([1, 1, 1]))


if __name__ == "__main__":
    unittest.main()
