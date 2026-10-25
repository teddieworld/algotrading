import unittest
from datetime import time
import pandas as pd
from orb_engine import run_orb


def bars(tail):
    rows = [('09:30', 100, 110, 100, 105), ('09:35',105,109,101,105),
            ('09:40',105,109,101,105)] + tail
    frame = pd.DataFrame(rows, columns=['time','Open','High','Low','Close'])
    frame.index = pd.to_datetime('2025-01-02 ' + frame.pop('time')).dt.tz_localize('America/New_York')
    frame['RiskFreeRate'] = 0.0
    return frame


class ExecutionTests(unittest.TestCase):
    def test_next_open_entry_and_ambiguous_stop(self):
        data = bars([('09:45',105,113,104,112),('09:50',114,130,99,120),('09:55',120,121,119,120)])
        trades, equity, daily = run_orb(data)
        t = trades.iloc[0]
        self.assertEqual(t.Entry_price,114)
        self.assertEqual(t.Exit_price,100)
        self.assertTrue(t.Ambiguous)
        self.assertAlmostEqual(t.Return, -29/25000)
        self.assertAlmostEqual(daily.Daily_Return.iloc[0],-29/25000)
        self.assertLess(daily.Drawdown.iloc[0],0)

    def test_gap_stop_and_short_session_flattening(self):
        data = bars([('09:45',105,113,104,112),('09:50',114,115,105,110),('09:55',95,98,90,96)])
        trades, _, _ = run_orb(data)
        self.assertEqual(trades.iloc[0].Exit_price,95)
        self.assertEqual(trades.iloc[0].Exit_reason,'gap_stop')
        data.loc[data.index[-1],['Open','High','Low','Close']] = [110,115,105,111]
        trades, _, daily = run_orb(data)
        self.assertEqual(trades.iloc[0].Exit_reason,'session_end')
        self.assertEqual(trades.iloc[0].Exit_price,111)
        self.assertEqual(len(daily),1)

    def test_missing_signal_followup_bar_cancels_order(self):
        data = bars([('09:45',105,113,104,112),('09:55',114,115,105,110),('10:00',110,111,105,108)])
        trades, _, _ = run_orb(data)
        self.assertTrue(trades.empty)

    def test_short_stop_and_target(self):
        data = bars([('09:45',105,106,97,98),('09:50',96,105,80,90),('09:55',90,95,85,90)])
        trades, _, _ = run_orb(data)
        self.assertEqual(trades.iloc[0].Position,'short')
        self.assertEqual(trades.iloc[0].Exit_price,82)
        self.assertEqual(trades.iloc[0].PnL,27)

    def test_afternoon_window_is_not_blocked_by_second_cutoff(self):
        data = bars([('13:00',105,113,104,112),('13:05',114,130,105,120),('13:10',120,121,119,120)])
        early, _, _ = run_orb(data, signal_end=time(12,25))
        late, _, _ = run_orb(data, signal_end=time(15,55))
        self.assertTrue(early.empty)
        self.assertEqual(len(late),1)
        self.assertEqual(late.iloc[0].Entry_time.time(),time(13,5))

    def test_incomplete_opening_range_no_trades(self):
        data = bars([('09:45',105,113,104,112),('09:50',114,130,99,120),('09:55',120,121,119,120)])
        trades, _, _ = run_orb(data.drop(data.index[1]))
        self.assertTrue(trades.empty)


if __name__ == '__main__':
    unittest.main()
