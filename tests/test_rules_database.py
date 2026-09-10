import json
import tempfile
import unittest
from pathlib import Path

from marvel_mcp_narrator.core.rules_database import (
    RulesLookupError,
    load_rules_database,
    lookup_rule_reference,
)


class RulesDatabaseTests(unittest.TestCase):
    def test_load_rules_database_from_packaged_resource(self):
        rules = load_rules_database()
        self.assertIn('references', rules)
        self.assertIn('basic_check', rules['references'])

    def test_lookup_rule_reference_returns_rule_key(self):
        payload = lookup_rule_reference('edge')
        self.assertEqual(payload['rule_key'], 'edge')
        self.assertEqual(payload['title'], 'Edge')

    def test_lookup_rule_reference_raises_for_unknown_key(self):
        with self.assertRaises(RulesLookupError):
            lookup_rule_reference('unknown_key')

    def test_load_and_lookup_with_explicit_path_override(self):
        content = {
            'references': {
                'custom_rule': {
                    'title': 'Custom Rule',
                    'summary': 'From temporary file',
                }
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'rules.json'
            path.write_text(json.dumps(content), encoding='utf-8')

            loaded = load_rules_database(path=path)
            self.assertEqual(loaded, content)

            payload = lookup_rule_reference('custom_rule', path=path)
            self.assertEqual(payload['rule_key'], 'custom_rule')
            self.assertEqual(payload['title'], 'Custom Rule')


if __name__ == '__main__':
    unittest.main()
