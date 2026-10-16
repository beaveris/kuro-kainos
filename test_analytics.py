import unittest
import pandas as pd
from analytics import stability_report, weekday_profile


class AnalyticsTests(unittest.TestCase):
    def test_top10_ties_and_small_municipality(self):
        rows = []
        for day in pd.bdate_range('2026-08-03', periods=10):
            for i in range(10):
                rows.append(dict(stotis_id=str(i), imone=str(i), miestas='Large',
                                 adresas=str(i), data=day.date(), kaina=1 if i < 2 else 2))
            rows.append(dict(stotis_id='small', imone='small', miestas='Small',
                             adresas='small', data=day.date(), kaina=1))
        report, n = stability_report(pd.DataFrame(rows))
        report = report.set_index('stotis_id')
        self.assertEqual(n, 10)
        self.assertEqual(report.loc['0', 'top10_pct'], 100)
        self.assertEqual(report.loc['1', 'top10_pct'], 100)
        self.assertTrue(pd.isna(report.loc['small', 'top10_pct']))
        self.assertTrue(pd.isna(report.loc['0', 'change_ct']))

    def test_repeatable_day_and_flat_week(self):
        dates = pd.bdate_range('2026-06-01', periods=50)
        prices = pd.Series([1.5 if d.weekday() == 2 else 1.7 for d in dates], index=dates)
        result = weekday_profile(prices)
        self.assertTrue(result['reliable'])
        self.assertEqual(result['best'], 2)
        self.assertEqual(result['wins'], 10)
        flat = weekday_profile(prices * 0 + 1.7)
        self.assertFalse(flat['reliable'])
        self.assertEqual(flat['wins'], 0)
        incomplete = weekday_profile(prices[prices.index.weekday != 4])
        self.assertEqual(incomplete['weeks'], 0)

    def test_recent_reversal_blocks_recommendation(self):
        dates = pd.bdate_range('2026-06-01', periods=50)
        prices = pd.Series([1.5 if d.weekday() == (2 if i < 30 else 0) else 1.7
                            for i, d in enumerate(dates)], index=dates)
        self.assertFalse(weekday_profile(prices)['reliable'])


if __name__ == '__main__':
    unittest.main()
