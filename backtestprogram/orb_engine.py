"""Five-minute, start-labeled bars; next-open ORB execution."""
from datetime import time
import numpy as np
import pandas as pd


def run_orb(data, initial_balance=25000, point_value=2, contracts=1,
            tp_ratio=1, commission=1, slippage_points=0,
            signal_start=time(9,45), signal_end=time(15,55)):
    """Commission is round trip per contract; slippage applies to market fills.

    Flatten at each day's last observed bar. This handles early closes but is
    only an approximation if a data outage truncates a session. Targets are
    limit orders filled at the target; ambiguous stop/target bars use stop first.
    """
    if not data.index.is_monotonic_increasing or data.index.has_duplicates:
        raise ValueError('Bars must be sorted with unique timestamps')
    balance = float(initial_balance)
    trades, equity, daily = [], [], []
    for date, bars in data.groupby(data.index.date):
        opening = bars.between_time('09:30', '09:40')
        complete = list(opening.index.time) == [time(9,30), time(9,35), time(9,40)]
        high = opening.High.max() if complete else np.nan
        low = opening.Low.min() if complete else np.nan
        width = high - low
        position = pending = None
        for number, (stamp, row) in enumerate(bars.iterrows()):
            last = number == len(bars) - 1
            # Pending signals expire across missing bars and never cross sessions.
            if pending is not None:
                direction, signal_stamp = pending
                if stamp - signal_stamp == pd.Timedelta(minutes=5) and not last:
                    fill = row.Open + direction * slippage_points
                    stop = low if direction == 1 else high
                    risk = direction * (fill - stop)
                    if risk > 0:
                        position = dict(direction=direction, entry=fill,
                                        stop=stop, target=fill + direction*risk*tp_ratio,
                                        stamp=stamp, risk=risk)
                pending = None
            if position is not None:
                p = position
                direction = p['direction']
                gap_stop = direction * (row.Open - p['stop']) <= 0
                hit_stop = row.Low <= p['stop'] if direction == 1 else row.High >= p['stop']
                hit_target = row.High >= p['target'] if direction == 1 else row.Low <= p['target']
                reason = None
                if gap_stop:
                    exit_price, reason = row.Open - direction*slippage_points, 'gap_stop'
                elif hit_stop:
                    exit_price, reason = p['stop'] - direction*slippage_points, 'stop'
                elif hit_target:
                    exit_price, reason = p['target'], 'target'
                elif last:
                    exit_price, reason = row.Close - direction*slippage_points, 'session_end'
                if reason:
                    pnl = direction*(exit_price-p['entry'])*point_value*contracts - commission*contracts
                    trade_return = pnl / balance
                    balance += pnl
                    trades.append(dict(Entry_time=p['stamp'], Entry_price=p['entry'],
                                       Exit_time=stamp, Exit_price=exit_price,
                                       Position='long' if direction == 1 else 'short',
                                       PnL=pnl, Return=trade_return, Balance=balance,
                                       ORB_Range=width, R=pnl/(p['risk']*point_value*contracts),
                                       Exit_reason=reason, Ambiguous=bool(hit_stop and hit_target)))
                    position = None
            # Closing-price signals are observed only after this bar finishes.
            if (position is None and not last and complete and stamp.month != 6
                    and 0 < width < 150 and signal_start <= stamp.time() <= signal_end):
                direction = 1 if row.Close > high else -1 if row.Close < low else 0
                if direction:
                    pending = (direction, stamp)
            unrealized = 0 if position is None else position['direction']*(row.Close-position['entry'])*point_value*contracts - commission*contracts
            equity.append((stamp, balance + unrealized))
        daily.append((bars.index[-1], balance, bars.iloc[-1].RiskFreeRate))
    columns = ['Entry_time','Entry_price','Exit_time','Exit_price','Position','PnL','Return','Balance','ORB_Range','R','Exit_reason','Ambiguous']
    trades = pd.DataFrame(trades, columns=columns)
    equity = pd.Series(dict(equity), name='Equity', dtype=float)
    daily = pd.DataFrame(daily, columns=['Date','Balance','RiskFreeRate']).set_index('Date')
    if daily.empty:
        raise ValueError('No session data')
    previous = daily.Balance.shift(1, fill_value=initial_balance)
    daily['Daily_Return'] = daily.Balance / previous - 1
    daily['Running_Peak'] = daily.Balance.cummax().clip(lower=initial_balance)
    daily['Drawdown'] = daily.Balance / daily.Running_Peak - 1
    daily['Excess_Return'] = daily.Daily_Return - daily.RiskFreeRate/252
    return trades, equity, daily
