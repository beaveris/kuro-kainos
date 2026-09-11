import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import history
from fuel_data import COLUMNS, DailyLink


class HistoryTests(unittest.TestCase):
    def test_distinct_operators_and_conflicting_prices(self):
        rows = [[company, 'Vilniaus m. sav.', 'Vilnius, Testo g. 1',
                 '95 benzinas', price, '2026-09-10']
                for company, price in [('A', 1.5), ('B', 1.6), ('C', 1.7), ('C', 1.8)]]
        rows += [[f'Other {i}', 'Vilniaus m. sav.', f'Testo g. {i+2}',
                  '95 benzinas', 1.5, '2026-09-10'] for i in range(100)]
        with tempfile.TemporaryDirectory() as directory, patch.object(history, 'DATA_DIR', Path(directory)):
            pd.DataFrame(rows, columns=COLUMNS).to_csv(history._day_path('2026-09-10'), index=False)
            result = history.load_history()
            self.assertEqual(result[result.imone.isin(['A', 'B'])].stotis_id.nunique(), 2)
            self.assertFalse((result.imone == 'C').any())

    def test_annual_import_keeps_larger_existing_day(self):
        row = ['A', 'Vilniaus m. sav.', 'Testo g. 1', '95 benzinas', 1.5]
        old = pd.DataFrame([row + ['2026-09-09'], ['B'] + row[1:] + ['2026-09-09']], columns=COLUMNS)
        incoming = pd.DataFrame([row + ['2026-09-09'], row + ['2026-09-10']], columns=COLUMNS)
        incoming['data'] = pd.to_datetime(incoming['data']).dt.date
        with tempfile.TemporaryDirectory() as directory, patch.object(history, 'DATA_DIR', Path(directory)), \
                patch.object(history, 'list_daily_links', return_value=[DailyLink('annual', 'test')]), \
                patch.object(history, 'download_daily_xlsx', return_value=b'test'), \
                patch.object(history, 'parse_daily_xlsx', return_value=incoming):
            path = history._day_path('2026-09-09')
            old.to_csv(path, index=False)
            before = path.read_bytes()
            self.assertEqual(history.sync(), ['2026-09-10'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(history.sync(), [])


if __name__ == '__main__':
    unittest.main()
