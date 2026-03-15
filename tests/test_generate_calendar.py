import datetime
import unittest

from generate_calendar import T, _local_feiertage, classify, fetch_year_feiertage
from models import LAND_CODES, PeriodConfig, YearConfig


def _local_fetcher(year, bundesland, verbose=True):
    return _local_feiertage(year, LAND_CODES[bundesland.lower()])


class GenerateCalendarTests(unittest.TestCase):
    def test_explicit_vacation_dates_are_applied_without_auto_fill(self):
        period = PeriodConfig(
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 12, 31),
            workdays={0, 1, 2, 3, 4},
            ho_days={0},
        )
        yc = YearConfig(
            year=2025,
            periods=[period],
            total_urlaub=4,
            explicit_urlaub_dates={
                datetime.date(2025, 4, 14),
                datetime.date(2025, 4, 15),
                datetime.date(2025, 4, 19),
            },
        )

        dm = classify(2025, {}, yc)

        self.assertEqual(dm[datetime.date(2025, 4, 14)][0], T.U)
        self.assertEqual(dm[datetime.date(2025, 4, 15)][0], T.U)
        self.assertEqual(dm[datetime.date(2025, 4, 19)][0], T.W)
        self.assertEqual(dm["_urlaub_mode"], "explicit")
        self.assertEqual(dm["_urlaub_allocated"], 2)
        self.assertEqual(dm["_urlaub_remaining"], 2)
        self.assertEqual(dm["_urlaub_ignored"], 1)

    def test_holidays_follow_period_states(self):
        yc = YearConfig(
            year=2025,
            periods=[
                PeriodConfig(
                    start_date=datetime.date(2025, 1, 1),
                    end_date=datetime.date(2025, 3, 31),
                    bundesland="Berlin",
                    land_code="BE",
                ),
                PeriodConfig(
                    start_date=datetime.date(2025, 4, 1),
                    end_date=datetime.date(2025, 12, 31),
                    bundesland="Hessen",
                    land_code="HE",
                ),
            ],
        )

        holidays = fetch_year_feiertage(yc, verbose=False, fetcher=_local_fetcher)

        self.assertIn(datetime.date(2025, 3, 8), holidays)
        self.assertIn(datetime.date(2025, 6, 19), holidays)
        self.assertNotIn(datetime.date(2025, 10, 31), holidays)


if __name__ == "__main__":
    unittest.main()
