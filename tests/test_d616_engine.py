import unittest

from marvel_mcp_narrator.core.d616_engine import roll_d616


class FixedRng:
    def __init__(self, values):
        self._values = iter(values)

    def randint(self, _a, _b):
        return next(self._values)


class D616EngineTests(unittest.TestCase):
    def test_trouble_kept_marvel_die_controls_fantastic(self):
        # initial marvel=6, trouble die=1, regular dice=2,3
        result = roll_d616(trouble=True, rng=FixedRng([6, 1, 2, 3]))
        self.assertEqual(result['marvel_die'], 1)
        self.assertTrue(result['fantastic'])
        self.assertEqual(result['total'], 12)

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
