import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import signal
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import websocket
from dotenv import load_dotenv

load_dotenv()

BASE_URL = 'https://demo.tradovateapi.com/v1'  # hard-coded demo safeguard
MD_URL = 'wss://md.tradovateapi.com/v1/websocket'
SYMBOL = os.getenv('TRADOVATE_SYMBOL', 'MNQZ6')
ACCOUNT_ID = int(os.getenv('TRADOVATE_ACCOUNT_ID', '0'))
ARM_ORDERS = os.getenv('TRADOVATE_ARM_ORDERS', 'false').lower() == 'true'
TZ = ZoneInfo('America/Los_Angeles')
ORB_START, ORB_END, CUTOFF = dtime(6, 30), dtime(6, 45), dtime(11, 55)
QTY, TP_RATIO, MAX_ORB_RANGE, TICK = 1, 1.5, 150.0, 0.25
MONITOR_SECONDS = 4
LOGDIR = Path(__file__).resolve().parent / 'logs'
logger = logging.getLogger('tradovate-orb')


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging():
    # Imports used by offline tests must not create files or duplicate handlers.
    LOGDIR.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return
    fmt = UTCFormatter('%(asctime)sZ %(levelname)s %(message)s')
    for handler in (logging.StreamHandler(), RotatingFileHandler(
            LOGDIR / 'tradovate_orb.log', maxBytes=5_000_000, backupCount=3)):
        handler.setFormatter(fmt)
        logger.addHandler(handler)

def now_local():
    return datetime.now(TZ)

def parse_ts(s):
    ts = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if ts.tzinfo is None:
        raise ValueError('Market-data timestamps must include a UTC offset')
    return ts.astimezone(TZ)

def rounded(x):
    return round(round(x / TICK) * TICK, 2)

def api_failure(data):
    if not isinstance(data, dict):
        return False
    return bool('p-ticket' in data or data.get('errorText') or data.get('failureText') or
                (data.get('failureReason') not in (None, 'Success')) or
                data.get('ok') is False)

class TradovateREST:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = requests.Session()
        self.token = None
        self.md_token = None
        self.expires_at = None
        self.authenticate()

    def authenticate(self):
        with self.lock:
            creds = {
                'name': os.environ['TRADOVATE_USERNAME'],
                'password': os.environ['TRADOVATE_PASSWORD'],
                'cid': os.environ['TRADOVATE_CID'],
                'sec': os.environ['TRADOVATE_SECRET'],
                'appId': os.getenv('TRADOVATE_APP_ID', 'ORBbot'),
                'appVersion': os.getenv('TRADOVATE_APP_VERSION', '1.0'),
            }
            r = self.session.post(BASE_URL + '/auth/accesstokenrequest', json=creds, timeout=20)
            r.raise_for_status()
            d = r.json()
            if 'accessToken' not in d or 'mdAccessToken' not in d:
                # Never include an authentication response: it can contain tokens.
                raise RuntimeError('Authentication failed or market-data token missing')
            self.token, self.md_token = d['accessToken'], d['mdAccessToken']
            self.expires_at = time.monotonic() + 65 * 60
            logger.info('Authenticated to Tradovate DEMO')

    def ensure_token(self):
        with self.lock:
            if time.monotonic() < self.expires_at:
                return
            r = self.session.get(BASE_URL + '/auth/renewaccesstoken',
                                 headers={'Authorization': f'Bearer {self.token}'}, timeout=15)
            r.raise_for_status()
            d = r.json()
            if 'accessToken' not in d:
                raise RuntimeError('Token renewal failed; manual restart required')
            self.token = d['accessToken']
            self.md_token = d.get('mdAccessToken', self.md_token)
            self.expires_at = time.monotonic() + 65 * 60
            logger.info('REST access token renewed')

    def get(self, endpoint, **params):
        self.ensure_token()
        with self.lock:
            r = self.session.get(BASE_URL + endpoint,
                                 headers={'Authorization': f'Bearer {self.token}'},
                                 params=params or None, timeout=15)
            r.raise_for_status()
            data = r.json()
            if api_failure(data):
                raise RuntimeError(f'{endpoint}: API rejected request (response withheld)')
            return data

    def post(self, endpoint, payload):
        # Defense in depth: every order mutation, including cancel and liquidation,
        # passes this gate before token renewal or any network request.
        if not ARM_ORDERS:
            raise RuntimeError('Order mutations disabled: TRADOVATE_ARM_ORDERS=false')
        if BASE_URL != 'https://demo.tradovateapi.com/v1':
            raise RuntimeError('Order mutations require the hard-coded DEMO endpoint')
        self.ensure_token()
        with self.lock:
            # NEVER automatically retry order POSTs: a timeout might mean the
            # server accepted the order and the response was lost.
            r = self.session.post(BASE_URL + endpoint,
                                  headers={'Authorization': f'Bearer {self.token}'},
                                  json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            if api_failure(data):
                raise RuntimeError(f'{endpoint}: API rejected request (response withheld)')
            return data

class ORBBot:
    def __init__(self):
        if ACCOUNT_ID <= 0:
            raise ValueError('Set TRADOVATE_ACCOUNT_ID explicitly in .env')
        self.api = TradovateREST()
        accounts = self.api.get('/account/list')
        matches = [a for a in accounts if int(a['id']) == ACCOUNT_ID]
        if len(matches) != 1:
            raise RuntimeError('Configured demo account ID was not found')
        self.account = matches[0]
        self.account_spec = self.account['name']
        contract = self.api.get('/contract/find', name=SYMBOL)
        self.contract_id = int(contract['id'])
        logger.info('Demo account ID %s, contract %s (%s), orders armed: %s',
                    ACCOUNT_ID, SYMBOL, self.contract_id, ARM_ORDERS)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.ws = None
        self.md_ready = False
        self.last_md = 0.0
        self.session_start = datetime.now(timezone.utc)
        self.chart_requested = False
        self.chart_ids = set()
        self.historical_id = None
        self.realtime_id = None
        self.live_bars = set()
        self.date = None
        self.bars = {}
        self.latest_ts = None
        self.completed = set()
        self.orb = None
        self.trade_active = False
        self.last_signal_ts = None
        self.entry_id = None
        self.exit_ids = set()
        self.order_pending = False
        self.entry_submitted_at = None
        self.seen_order_statuses = {}
        self.halted = False
        self.cutoff_attempted = False
        self.reconcile_initial()
        threading.Thread(target=self.monitor, daemon=True).start()

    def positions(self):
        return [p for p in self.api.get('/position/list') if
                int(p.get('accountId', -1)) == ACCOUNT_ID and
                int(p.get('contractId', -1)) == self.contract_id and
                int(p.get('netPos') or 0) != 0]

    def working_orders(self):
        active = {'Working', 'Accepted', 'PendingNew', 'PendingCancel',
                  'PendingReplace', 'Suspended', 'PartiallyFilled'}
        return [o for o in self.api.get('/order/list') if
                int(o.get('accountId', -1)) == ACCOUNT_ID and
                int(o.get('contractId', -1)) == self.contract_id and
                o.get('ordStatus') in active]

    def reconcile_initial(self):
        if self.positions() or self.working_orders():
            raise RuntimeError('Existing MNQ position or working orders on account; '
                               'refusing to start until manually reconciled')
        logger.info('Startup reconciliation: account flat, no working MNQ orders')

    def reset_day(self, date):
        # Do not discard real exchange order state when resetting market-data state.
        self.date = date
        self.bars.clear()
        self.completed.clear()
        self.live_bars.clear()
        self.latest_ts = None
        self.orb = None
        self.last_signal_ts = None
        self.cutoff_attempted = False
        logger.info('New trading date %s', date)

    def process_bar(self, raw, *, allow_entry=False):
        if any(raw.get(k) is None for k in ('timestamp', 'open', 'high', 'low', 'close')):
            return
        try:
            ts = parse_ts(raw['timestamp'])
            values = [float(raw[k]) for k in ('open', 'high', 'low', 'close')]
            op, high, low, close = values
            if (not all(math.isfinite(v) and v > 0 for v in values) or
                    not low <= min(op, close) <= max(op, close) <= high or
                    ts.minute % 5 or ts.second or ts.microsecond):
                raise ValueError('Invalid five-minute OHLC candle')
        except (TypeError, ValueError, AttributeError):
            self.halted = True
            logger.error('Invalid candle or timestamp; new entries halted')
            return
        if ts.date() != now_local().date():
            return
        if not (ORB_START <= ts.time() < CUTOFF):
            return
        with self.lock:
            if self.date != ts.date():
                self.reset_day(ts.date())
            # Completed candles are immutable. Historical replies may arrive after
            # live updates and must not replace a live candle with an older copy.
            if ts in self.completed or (not allow_entry and ts in self.live_bars):
                return
            bar = {'Date': ts, 'Open': float(raw['open']), 'High': float(raw['high']),
                   'Low': float(raw['low']), 'Close': float(raw['close']),
                   'Volume': float(raw.get('upVolume') or 0) + float(raw.get('downVolume') or 0)}
            self.bars[ts] = bar
            if allow_entry and ts <= now_local() < ts + timedelta(minutes=5):
                self.live_bars.add(ts)
            if self.latest_ts is None:
                self.latest_ts = ts
                return
            if ts <= self.latest_ts:
                return
            old = self.latest_ts
            self.latest_ts = ts
            if ts - old != timedelta(minutes=5):
                logger.warning('Missing 5-minute candles between %s and %s; signals disabled until next session', old, ts)
                self.halted = True
                return
            if old in self.completed:
                return
            self.completed.add(old)
            self.completed_bar(self.bars[old], allow_entry=allow_entry and old in self.live_bars)

    def completed_bar(self, bar, *, allow_entry=False):
        ts = bar['Date']
        logger.info('BAR %s OHLCV %s %s %s %s %s', ts.isoformat(),
                    bar['Open'], bar['High'], bar['Low'], bar['Close'], bar['Volume'])
        if self.orb is None:
            starts = [datetime.combine(self.date, dtime(6, m), TZ) for m in (30, 35, 40)]
            if all(t in self.completed for t in starts):
                sample = [self.bars[t] for t in starts]
                high = max(b['High'] for b in sample)
                low = min(b['Low'] for b in sample)
                self.orb = (high, low)
                logger.info('ORB high=%s low=%s range=%s', high, low, high - low)
        if allow_entry:
            self.check_entry(bar)

    def check_entry(self, bar):
        if self.orb is None or self.trade_active or self.halted or self.order_pending:
            return
        if self.last_signal_ts is not None and bar['Date'] <= self.last_signal_ts:
            return
        if not self.md_ready or time.monotonic() - self.last_md > 25:
            return
        now = now_local()
        if now.date() != bar['Date'].date() or not ORB_END <= now.time() < CUTOFF:
            return
        high, low = self.orb
        if not 0 < high - low < MAX_ORB_RANGE:
            return
        close_dt = bar['Date'] + timedelta(minutes=5)
        if close_dt.time() <= ORB_END or close_dt.time() >= CUTOFF:
            return
        # Disallow historical/delayed signals, especially after reconnect.
        delay = (datetime.now(timezone.utc) - close_dt.astimezone(timezone.utc)).total_seconds()
        if not (0 <= delay <= 60) or close_dt.astimezone(timezone.utc) < self.session_start:
            return
        close = bar['Close']
        if close > high:
            side, stop = 'Buy', rounded(low)
            target = rounded(close + (close - stop) * TP_RATIO)
        elif close < low:
            side, stop = 'Sell', rounded(high)
            target = rounded(close - (stop - close) * TP_RATIO)
        else:
            return
        if min(stop, target) <= 0:
            return
        logger.info('SIGNAL %s close=%s stop=%s target=%s', side, close, stop, target)
        self.last_signal_ts = bar['Date']  # Each completed candle can signal only once.
        if not ARM_ORDERS:
            logger.warning('DRY RUN: orders disabled. Set TRADOVATE_ARM_ORDERS=true after verification.')
            return
        self.submit_bracket(side, stop, target)

    def submit_bracket(self, side, stop, target):
        if not ARM_ORDERS:
            logger.warning('DRY RUN: bracket submission blocked')
            return
        self.trade_active = True  # Keep locked through uncertain submission outcomes.
        self.order_pending = True
        exit_side = 'Sell' if side == 'Buy' else 'Buy'
        body = {
            'accountSpec': self.account_spec, 'accountId': ACCOUNT_ID,
            'action': side, 'symbol': SYMBOL, 'orderQty': QTY,
            'orderType': 'Market', 'isAutomated': True,
            'bracket1': {'action': exit_side, 'orderType': 'Stop', 'stopPrice': stop},
            'bracket2': {'action': exit_side, 'orderType': 'Limit', 'price': target},
        }
        try:
            # A single parent+OCO-children instruction reduces naked-order risk.
            result = self.api.post('/order/placeoso', body)
            self.entry_id = result.get('orderId')
            self.exit_ids = {i for i in (result.get('oso1Id'), result.get('oso2Id')) if i}
            if not self.entry_id or len(self.exit_ids) != 2:
                raise RuntimeError('OSO returned unexpected IDs; reconcile broker state')
            self.entry_submitted_at = time.monotonic()
            logger.warning('OSO SUBMITTED entry=%s children=%s; monitoring broker state',
                           self.entry_id, sorted(self.exit_ids))
        except Exception:
            logger.exception('ORDER STATE UNKNOWN after submission. HALTING; inspect Tradovate immediately.')
            self.halted = True
        finally:
            self.order_pending = False

    def monitor(self):
        # Reconcile REST account state instead of assuming HTTP success == fill.
        while not self.stop_event.wait(MONITOR_SECONDS):
            try:
                with self.lock:
                    now = now_local()
                    if self.date and self.date != now.date():
                        self.halted = True
                        logger.error('Day changed without restart. HALTING. Restart after checking account.')
                    positions = self.positions()
                    working = self.working_orders()
                    relevant_orders = {int(o['id']): o for o in self.api.get('/order/list')
                                       if int(o.get('accountId', -1)) == ACCOUNT_ID}
                    for oid in [self.entry_id, *sorted(self.exit_ids)]:
                        if oid is None:
                            continue
                        order = relevant_orders.get(int(oid))
                        if order:
                            status = order.get('ordStatus')
                            if self.seen_order_statuses.get(int(oid)) != status:
                                self.seen_order_statuses[int(oid)] = status
                                logger.info('ORDER UPDATE id=%s status=%s', oid, status)
                                if status == 'Filled':
                                    logger.info('ORDER FILLED id=%s (inspect execution reports for fill price)', oid)
                    if self.entry_id is not None:
                        parent = relevant_orders.get(int(self.entry_id))
                        children = [relevant_orders.get(int(i)) for i in self.exit_ids]
                        if parent and parent.get('ordStatus') in ('Rejected', 'Canceled'):
                            self.halted = True
                            logger.error('Parent order terminal status=%s; trading halted', parent.get('ordStatus'))
                        if positions:
                            child_statuses = [c.get('ordStatus') if c else None for c in children]
                            # A filled exit normally cancels its OCO sibling; allow
                            # reconciliation of the closing position before intervening.
                            if 'Filled' in child_statuses:
                                continue
                            dangerous = any(st in ('Rejected', 'Canceled') for st in child_statuses)
                            # Allow a short window for child order propagation, but do not
                            # silently run with a naked position if they never materialize.
                            grace_expired = (self.entry_submitted_at is not None and
                                             time.monotonic() - self.entry_submitted_at > 12)
                            missing = grace_expired and any(st is None for st in child_statuses)
                            if dangerous or missing:
                                logger.critical('PROTECTION NOT VERIFIED (%s). HALT + liquidation request.', child_statuses)
                                self.halted = True
                                self.liquidate()
                    if now.time() >= CUTOFF and not self.cutoff_attempted:
                        self.cutoff_attempted = True
                        self.halted = True
                        if positions:
                            logger.warning('11:55 cutoff: requesting cancel+liquidation for MNQ')
                            self.liquidate()
                        elif working:
                            logger.warning('11:55 cutoff: canceling working MNQ orders while flat')
                            for order in working:
                                self.cancel_order(int(order['id']))
                        else:
                            logger.info('11:55 cutoff: flat and no working orders')
                    self.complete_trade_if_flat(positions, working, relevant_orders)
            except Exception:
                self.halted = True
                logger.exception('Account reconciliation failed. HALTING NEW SIGNALS. Inspect account immediately.')

    def complete_trade_if_flat(self, positions, working, orders):
        # Flat alone is insufficient: a submitted parent may not have filled yet.
        # Re-entry requires a filled parent, one filled exit, and its canceled OCO
        # sibling, followed by a fresh check for remaining exposure and orders.
        if (not self.trade_active or self.halted or self.order_pending or
                positions or working or self.entry_id is None or len(self.exit_ids) != 2):
            return
        parent = orders.get(int(self.entry_id))
        children = [orders.get(int(oid)) for oid in self.exit_ids]
        if not parent or parent.get('ordStatus') != 'Filled' or not all(children):
            return
        if sorted(child.get('ordStatus') or '' for child in children) != ['Canceled', 'Filled']:
            return
        if self.positions() or self.working_orders():
            return
        self.trade_active = False
        self.entry_id = None
        self.exit_ids.clear()
        self.entry_submitted_at = None
        self.seen_order_statuses.clear()
        logger.info('Trade closed and orders cleared; next completed-candle breakout eligible')

    def cancel_order(self, order_id):
        if not ARM_ORDERS:
            logger.warning('DRY RUN: cancellation blocked for id=%s', order_id)
            return
        try:
            result = self.api.post('/order/cancelorder', {
                'orderId': order_id, 'isAutomated': True,
            })
            logger.warning('CANCEL REQUEST id=%s result=%s (not yet confirmed canceled)', order_id, result)
        except Exception:
            logger.exception('CANCEL UNKNOWN for id=%s. Inspect Tradovate manually.', order_id)

    def liquidate(self):
        if not ARM_ORDERS:
            logger.critical('DRY RUN: liquidation blocked; any existing position requires manual management')
            return
        try:
            response = self.api.post('/order/liquidateposition', {
                'accountId': ACCOUNT_ID, 'contractId': self.contract_id,
                'admin': False, 'isAutomated': True,
            })
            logger.warning('LIQUIDATION REQUEST response=%s; NOT proof of flat account', response)
        except Exception:
            logger.exception('LIQUIDATION FAILED/UNKNOWN: manually verify and flatten Tradovate NOW')

    def subscribe(self, ws):
        request = {
            'symbol': SYMBOL,
            'chartDescription': {'underlyingType': 'MinuteBar', 'elementSize': 5,
                                 'elementSizeUnit': 'UnderlyingUnits', 'withHistogram': False},
            'timeRange': {'asMuchAsElements': 100},
        }
        ws.send('md/getChart\n1\n\n' + json.dumps(request))
        self.chart_requested = True
        logger.info('Requested chart data for %s', SYMBOL)

    def on_open(self, ws):
        self.md_ready = False
        self.chart_requested = False
        self.chart_ids = set()
        self.historical_id = None
        self.realtime_id = None
        self.live_bars.clear()
        self.last_md = 0.0
        ws.send(f'authorize\n0\n\n{self.api.md_token}')
        logger.info('Market data websocket open')
        threading.Thread(target=self.heartbeat, args=(ws,), daemon=True).start()

    def heartbeat(self, ws):
        while not self.stop_event.wait(2.5):
            if ws is not self.ws:
                return
            try:
                ws.send('[]')
            except Exception:
                return

    def on_message(self, ws, message):
        if ws is not self.ws:
            return  # A callback from a retired connection cannot update this one.
        try:
            self.handle_message(ws, message)
        except (ValueError, TypeError, AttributeError, RuntimeError):
            self.md_ready = False
            self.halted = True
            # Do not log raw frames or exception text: authorization errors may
            # contain sensitive data. Close so the reconnect loop takes over.
            logger.error('Invalid or rejected market-data message; entries halted')
            ws.close()

    def handle_message(self, ws, message):
        if message in ('o', 'h'):
            return
        if message and message[0] == 'c':
            raise RuntimeError('Server closed market-data session')
        if not message or message[0] != 'a':
            return
        items = json.loads(message[1:])
        if not isinstance(items, list):
            raise ValueError('Expected a message array')
        for item in items:
            if item.get('i') == 0:
                if item.get('s') != 200:
                    raise RuntimeError('MD authorization failed')
                if not self.chart_requested:
                    self.subscribe(ws)
            elif item.get('i') == 1:
                if item.get('s') != 200:
                    raise RuntimeError('MD chart request failed')
                data = item.get('d') or {}
                self.historical_id = data.get('historicalId')
                self.realtime_id = data.get('realtimeId')
                if (self.historical_id is None or self.realtime_id is None or
                        self.historical_id == self.realtime_id):
                    raise RuntimeError('Missing or ambiguous chart subscription IDs')
                self.chart_ids = {self.historical_id, self.realtime_id}
                self.md_ready = True
                logger.info('Chart subscription confirmed ids=%s', self.chart_ids)
            elif item.get('e') == 'chart':
                charts = (item.get('d') or {}).get('charts') or []
                with self.lock:
                    for chart in charts:
                        if not self.md_ready or chart.get('id') not in self.chart_ids:
                            continue
                        bars = sorted(chart.get('bars') or [], key=lambda b: b.get('timestamp', ''))
                        realtime = chart.get('id') == self.realtime_id
                        if bars and realtime:
                            self.last_md = time.monotonic()
                        for bar in bars:
                            self.process_bar(bar, allow_entry=realtime)

    def on_error(self, ws, error):
        self.md_ready = False
        logger.error('WebSocket failure: %s', error)

    def on_close(self, ws, code, reason):
        self.md_ready = False
        logger.warning('WebSocket closed %s %s', code, reason)

    def run(self):
        # This intentionally HALTS on disconnect after market open: a reconnect
        # requires independent account+order reconciliation before arming again.
        while not self.stop_event.is_set():
            try:
                self.api.ensure_token()
                self.session_start = datetime.now(timezone.utc)
                self.ws = websocket.WebSocketApp(
                    MD_URL, on_open=self.on_open, on_message=self.on_message,
                    on_error=self.on_error, on_close=self.on_close)
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                logger.exception('Market-data loop exception')
            self.md_ready = False
            if ORB_START <= now_local().time() < CUTOFF:
                self.halted = True
                logger.critical('MD disconnected during session; new entries disabled until manual restart/reconciliation')
            if self.stop_event.wait(5):
                break
        logger.info('Bot stopped; existing exchange orders NOT canceled automatically')

    def stop(self, *_):
        self.stop_event.set()
        if self.ws:
            self.ws.close()


if __name__ == '__main__':
    configure_logging()
    bot = ORBBot()
    signal.signal(signal.SIGINT, bot.stop)
    signal.signal(signal.SIGTERM, bot.stop)
    bot.run()
