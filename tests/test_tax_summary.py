import datetime
import unittest

from generate_calendar import T
from models import AdditionalExpense, PeriodConfig, YearConfig
from tax_summary import compute_werbungskosten, entfernungspauschale


class TaxSummaryTests(unittest.TestCase):
    def test_entfernungspauschale_2026_uses_single_rate_from_first_kilometer(self):
        self.assertAlmostEqual(entfernungspauschale(25, 10, 2026), 95.0)

    def test_unsupported_tax_year_raises(self):
        with self.assertRaises(ValueError):
            entfernungspauschale(25, 10, 2027)

    def test_additional_expenses_are_included_in_total(self):
        period = PeriodConfig(
            start_date=datetime.date(2025, 1, 2),
            end_date=datetime.date(2025, 1, 3),
            km=25.0,
        )
        yc = YearConfig(
            year=2025,
            periods=[period],
            additional_expenses=[
                AdditionalExpense("Arbeitsmittel", 120.0, "Monitor"),
                AdditionalExpense("Kontofuehrung", 16.0),
            ],
        )
        dm = {
            datetime.date(2025, 1, 2): (T.B, ""),
            datetime.date(2025, 1, 3): (T.H, ""),
        }

        result = compute_werbungskosten(2025, yc, dm)

        self.assertEqual(result.total_buero, 1)
        self.assertEqual(result.total_ho, 1)
        self.assertAlmostEqual(result.total_ep, 7.9)
        self.assertAlmostEqual(result.additional_expenses_total, 136.0)
        self.assertAlmostEqual(result.werbungskosten_total, 149.9)


if __name__ == "__main__":
    unittest.main()
