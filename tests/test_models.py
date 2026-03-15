import json
import tempfile
import unittest
from pathlib import Path

from models import load_metadata, validate_metadata


class ModelsTests(unittest.TestCase):
    def test_metadata_parses_explicit_vacation_and_additional_expenses(self):
        metadata = {
            "Vorname": "Max",
            "Nachname": "Mustermann",
            "Werbungskosten": {
                "2025": [
                    {
                        "Kategorie": "Arbeitsmittel",
                        "Beschreibung": "Headset",
                        "Betrag": "89,90",
                    }
                ]
            },
            "Jahr": {
                "2025": [
                    {
                        "Arbeitstage": "Montag bis Freitag",
                        "Feiertage": "Berlin",
                        "Home-Office-Tage": "Montag",
                        "Urlaubstage": "5",
                        "Urlaubsdaten": [
                            "14.04.2025 - 15.04.2025",
                            "30.05.2025",
                        ],
                        "Kilometer_Entfernung": "8",
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "metadata.json"
            path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

            _, year_configs = load_metadata(path)

        yc = year_configs[0]
        self.assertEqual(len(yc.explicit_urlaub_dates), 3)
        self.assertEqual(len(yc.additional_expenses), 1)
        self.assertEqual(yc.additional_expenses[0].category, "Arbeitsmittel")
        self.assertAlmostEqual(yc.additional_expenses[0].amount, 89.9)

    def test_validation_warns_when_only_partial_vacation_is_documented(self):
        metadata = {
            "Jahr": {
                "2025": [
                    {
                        "Arbeitstage": "Montag bis Freitag",
                        "Feiertage": "Berlin",
                        "Urlaubstage": "3",
                        "Urlaubsdaten": ["14.04.2025"],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "metadata.json"
            path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

            _, year_configs = load_metadata(path)

        issues = validate_metadata(year_configs)

        self.assertTrue(any("nur 1 nutzbare Urlaubstage dokumentiert" in issue.message for issue in issues))


if __name__ == "__main__":
    unittest.main()
