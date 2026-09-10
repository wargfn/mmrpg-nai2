import unittest

from marvel_mcp_narrator.mcp_servers import narrator_tools


class NarratorToolsTests(unittest.TestCase):
    def test_roll_d616_tool_uses_public_name(self):
        self.assertTrue(callable(narrator_tools.roll_d616))

    def test_lookup_rule_returns_exact_rule_reference_payload(self):
        payload = narrator_tools.lookup_rule("d616_basics")
        self.assertEqual(payload["rule_key"], "d616_basics")
        self.assertEqual(payload["entry_type"], "mechanic")


if __name__ == "__main__":
    unittest.main()
