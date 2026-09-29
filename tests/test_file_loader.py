import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marvel_mcp_narrator.core.character_state import CharacterRoster
from marvel_mcp_narrator.core.file_loader import UnifiedContextInjector
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase


class UnifiedContextInjectorTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.data_dir = self.base_path / "data"
        self.notebook_dir = self.data_dir / "notebooks"
        self.data_dir.mkdir()
        self.notebook_dir.mkdir(parents=True)
        self.database = CampaignDatabase(self.base_path / "campaign.db")
        self.roster = CharacterRoster()
        self.injector = UnifiedContextInjector(
            campaign_database=self.database,
            character_roster_store=self.roster,
            data_directory=self.data_dir,
            notebook_directory=self.notebook_dir,
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_load_local_json_files_reads_data_directory(self):
        (self.data_dir / "rules.json").write_text('{"mechanics":{"edge":{"description":"Keep the best die."}}}', encoding="utf-8")

        payload = self.injector.load_local_json_files()

        self.assertIn("rules.json", payload)
        self.assertEqual(payload["rules.json"]["mechanics"]["edge"]["description"], "Keep the best die.")

    def test_load_notebook_sources_reads_markdown_exports(self):
        (self.notebook_dir / "field-notes.md").write_text("# Field Notes\nHydra medbay readiness checklist.", encoding="utf-8")

        payload = self.injector.load_notebook_sources()

        self.assertEqual(payload["field-notes.md"], "# Field Notes\nHydra medbay readiness checklist.")

    def test_build_context_block_includes_character_rules_campaign_and_notebook_matches(self):
        (self.data_dir / "rules.json").write_text(
            '{"mechanics":{"edge":{"title":"Edges and Troubles","description":"Roll with Edge to keep the best die."}}}',
            encoding="utf-8",
        )
        (self.notebook_dir / "paramedic.md").write_text(
            "Paramedic readiness guidance for Hydra toxins and Oscorp antidote kits.",
            encoding="utf-8",
        )
        self.roster.create_or_load(
            name="Spider-Man",
            archetype="Striker",
            rank=4,
            melee=4,
            agility=6,
            resilience=3,
            vigilance=4,
            ego=3,
            logic=4,
            traits=["wisecracking"],
            tags=["street hero"],
        )
        self.database.create_campaign_plan(
            theme="Hydra Infiltration",
            villain="Red Skull",
            hero_team=["Spider-Man"],
            sessions=[
                {
                    "session_number": 1,
                    "title": "Oscorp Under Siege",
                    "objectives": ["Rescue Oscorp scientists"],
                    "key_npcs": ["Dr. Connors"],
                    "locations": ["Oscorp Tower"],
                    "completion_milestone": "Secure the antidote",
                }
            ],
        )
        self.database.save_memory("session-1", "Hydra agents stole Oscorp toxin samples.")
        self.database.save_previous_campaign_events_summary("Spider-Man previously stopped a Hydra breakout.")

        context = self.injector.build_context_block(
            "Can Spider-Man use edge while responding to the Hydra crisis with paramedic support at Oscorp?"
        )

        self.assertIn("Relevant Character Sheets:", context)
        self.assertIn("Spider-Man", context)
        self.assertIn("[System Context - Automated Rule Citation: Edges and Troubles]", context)
        self.assertIn('"description": "Roll with Edge to keep the best die."', context)
        self.assertIn("Relevant Campaign Context:", context)
        self.assertIn("Previous events:", context)
        self.assertIn("[System Context - Automated Notebook Citation: paramedic.md]", context)
        self.assertIn("Paramedic readiness guidance", context)

    def test_scan_prompt_for_keywords_matches_power_family_and_power_set_entries(self):
        (self.data_dir / "rules.json").write_text(
            json.dumps(
                {
                    "mechanics": {},
                    "power_sets": [
                        {
                            "name": "Elemental Control",
                            "powers": [
                                {"name": "Mighty 1", "rank_required": 1, "prerequisites": []},
                                {"name": "Mighty 2", "rank_required": 2, "prerequisites": ["Mighty 1"]},
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        matches = self.injector.scan_prompt_for_keywords("Can Elemental Control stack with Mighty during this scene?")

        self.assertEqual(len(matches["rules"]), 2)
        self.assertIn("Elemental Control", matches["rules"][0]["block"] + matches["rules"][1]["block"])
        self.assertIn("[System Context - Automated Rule Citation: Mighty]", matches["rules"][0]["block"] + matches["rules"][1]["block"])
        self.assertIn('"name": "Mighty 1"', matches["rules"][0]["block"] + matches["rules"][1]["block"])


if __name__ == "__main__":
    unittest.main()
