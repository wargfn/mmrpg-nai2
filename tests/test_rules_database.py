import json
import tempfile
import unittest
from pathlib import Path

from marvel_mcp_narrator.core.rules_database import (
    RulesDatabase,
    RulesLookupError,
    load_rules_database,
    lookup_rule_reference,
    query_rulebook_database,
)


class RulesDatabaseTests(unittest.TestCase):
    def test_load_rules_database_from_packaged_resource(self):
        rules = load_rules_database()
        self.assertIn('mechanics', rules)
        self.assertIn('powers', rules)
        self.assertIn('d616_basics', rules['mechanics'])

    def test_query_rulebook_database_finds_mechanics(self):
        results = query_rulebook_database('fantastic')
        self.assertIn('Rulebook Search Results', results)
        self.assertIn('Fantastic Roll', results)
        self.assertIn('### Mechanics', results)

    def test_query_rulebook_database_finds_powers(self):
        results = query_rulebook_database('teleport')
        self.assertIn('### Powers', results)
        self.assertIn('Teleportation', results)

    def test_query_rulebook_database_handles_no_match(self):
        results = query_rulebook_database('not-a-real-rule')
        self.assertIn('No rulebook matches found', results)

    def test_rules_database_class_query_rules(self):
        db = RulesDatabase()
        results = db.query_rules('ranged')
        self.assertIn('Blast', results)

    def test_lookup_rule_reference_returns_mechanic(self):
        payload = lookup_rule_reference('d616_basics')
        self.assertEqual(payload['rule_key'], 'd616_basics')
        self.assertIn('title', payload)

    def test_lookup_rule_reference_raises_for_unknown_key(self):
        with self.assertRaises(RulesLookupError):
            lookup_rule_reference('unknown_key')

    def test_load_and_query_with_explicit_path_override(self):
        content = {
            'mechanics': {
                'custom_rule': {
                    'title': 'Custom Rule',
                    'category': 'Mechanics',
                    'description': 'From temporary file'
                }
            },
            'powers': [
                {
                    'name': 'Shadow Step',
                    'category': 'Movement',
                    'rank_required': 1,
                    'description': 'Short-range teleportation between shadows.'
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'rules.json'
            path.write_text(json.dumps(content), encoding='utf-8')

            loaded = load_rules_database(path=path)
            self.assertEqual(loaded, content)

            db = RulesDatabase(path=path)
            results = db.query_rules('shadow')
            self.assertIn('Shadow Step', results)

            payload = lookup_rule_reference('custom_rule', path=path)
            self.assertEqual(payload['rule_key'], 'custom_rule')
            self.assertEqual(payload['title'], 'Custom Rule')


if __name__ == '__main__':
    unittest.main()
