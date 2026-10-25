"""Focused offline checks for multiple trades per session."""
import importlib
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests


with patch('dotenv.load_dotenv'), patch.dict(os.environ, {
        'TRADOVATE_ACCOUNT_ID': '123', 'TRADOVATE_ARM_ORDERS': 'false'}, clear=True):
    module = importlib.import_module('execution.tradovate_orb_demo')


class ReentryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(requests.sessions.Session, 'request',
                     side_effect=AssertionError('Network forbidden in offline tests')).start()
        patch.object(module, 'ARM_ORDERS', True).start()
        patch.object(module.logger, 'disabled', True).start()
        self.now = datetime(2026, 10, 23, 6, 50, tzinfo=module.TZ)
        patch.object(module, 'now_local', side_effect=lambda: self.now).start()
        clock = patch.object(module, 'datetime', Mock(wraps=datetime)).start()
        clock.now.side_effect = lambda tz=None: self.now.astimezone(tz)
        self.bot = object.__new__(module.ORBBot)
        self.bot.lock = threading.RLock()
        self.bot.date = self.now.date()
        self.bot.orb = (110, 100)
        self.bot.md_ready = True
        self.bot.last_md = time.monotonic()
        self.bot.session_start = (self.now - timedelta(hours=1)).astimezone(timezone.utc)
        self.bot.trade_active = False
        self.bot.last_signal_ts = None
        self.bot.halted = False
        self.bot.order_pending = False
        self.bot.entry_id = None
        self.bot.exit_ids = set()
        self.bot.entry_submitted_at = None
        self.bot.seen_order_statuses = {}
        self.bot.cutoff_attempted = False
        self.bot.account_spec = 'offline-demo'
        self.bot.api = Mock()
        self.bot.api.post.return_value = {'orderId': 1, 'oso1Id': 2, 'oso2Id': 3}
        self.bot.positions = Mock(return_value=[])
        self.bot.working_orders = Mock(return_value=[])
        self.orders = {1: {'id': 1, 'ordStatus': 'Filled'},
                       2: {'id': 2, 'ordStatus': 'Filled'},
                       3: {'id': 3, 'ordStatus': 'Canceled'}}

    def signal(self):
        return {'Date': self.now - timedelta(minutes=5), 'Close': 112}

    def enter(self):
        self.bot.check_entry(self.signal())
        self.assertTrue(self.bot.trade_active)

    def test_second_trade_can_enter_after_confirmed_close(self):
        self.enter()
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertFalse(self.bot.trade_active)
        self.assertIsNone(self.bot.entry_id)
        self.assertEqual(self.bot.exit_ids, set())
        self.now += timedelta(minutes=5)
        self.bot.check_entry(self.signal())
        self.assertEqual(self.bot.api.post.call_count, 2)

    def test_open_trade_blocks_another_signal(self):
        self.enter()
        self.now += timedelta(minutes=5)
        self.bot.check_entry(self.signal())
        self.bot.api.post.assert_called_once()

    def test_same_candle_cannot_reenter_after_exit(self):
        self.enter()
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.bot.check_entry(self.signal())
        self.bot.api.post.assert_called_once()

    def test_flat_snapshot_does_not_unlock_pending_parent(self):
        self.enter()
        self.orders[1]['ordStatus'] = 'Working'
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertTrue(self.bot.trade_active)

    def test_unconfirmed_or_failed_child_does_not_unlock(self):
        self.enter()
        for status in ('Working', 'PendingCancel', 'Suspended', 'Rejected', 'Expired', None):
            with self.subTest(status=status):
                self.orders[3]['ordStatus'] = status
                self.bot.complete_trade_if_flat([], [], self.orders)
                self.assertTrue(self.bot.trade_active)
        del self.orders[3]
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertTrue(self.bot.trade_active)

    def test_remaining_position_or_working_orders_prevent_unlock(self):
        self.enter()
        self.bot.complete_trade_if_flat([{'netPos': 1}], [], self.orders)
        self.assertTrue(self.bot.trade_active)
        self.bot.complete_trade_if_flat([], [{'ordStatus': 'Working'}], self.orders)
        self.assertTrue(self.bot.trade_active)

    def test_fresh_exposure_check_prevents_unlock_from_stale_snapshot(self):
        self.enter()
        self.bot.positions.return_value = [{'netPos': 1}]
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertTrue(self.bot.trade_active)
        self.bot.positions.return_value = []
        self.bot.working_orders.return_value = [{'ordStatus': 'Working'}]
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertTrue(self.bot.trade_active)

    def test_halt_and_uncertain_submission_remain_locked(self):
        self.bot.api.post.side_effect = requests.Timeout('offline timeout')
        self.enter()
        self.assertTrue(self.bot.halted)
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.assertTrue(self.bot.trade_active)
        self.now += timedelta(minutes=5)
        self.bot.check_entry(self.signal())
        self.bot.api.post.assert_called_once()

    def test_monitor_releases_completed_trade(self):
        self.enter()
        self.bot.stop_event = Mock()
        self.bot.stop_event.wait.side_effect = [False, True]
        self.bot.api.get.return_value = [dict(order, accountId=module.ACCOUNT_ID)
                                       for order in self.orders.values()]
        self.bot.monitor()
        self.assertFalse(self.bot.trade_active)

    def test_disarmed_mode_logs_multiple_candles_without_order_submission(self):
        with patch.object(module, 'ARM_ORDERS', False):
            self.bot.check_entry(self.signal())
            self.now += timedelta(minutes=5)
            self.bot.check_entry(self.signal())
        self.assertFalse(self.bot.trade_active)
        self.assertEqual(self.bot.last_signal_ts, self.signal()['Date'])
        self.bot.api.post.assert_not_called()

    def test_cutoff_still_blocks_next_entry(self):
        self.enter()
        self.bot.complete_trade_if_flat([], [], self.orders)
        self.now = self.now.replace(hour=11, minute=55)
        self.bot.check_entry(self.signal())
        self.bot.api.post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
