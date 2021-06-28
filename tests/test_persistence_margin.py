import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import FunctionType
from unittest.mock import MagicMock
import arrow
import pytest
from math import isclose
from sqlalchemy import create_engine, inspect, text
from freqtrade import constants
from freqtrade.exceptions import DependencyException, OperationalException
from freqtrade.persistence import LocalTrade, Order, Trade, clean_dry_run_db, init_db
from tests.conftest import create_mock_trades, log_has, log_has_re


@pytest.mark.usefixtures("init_persistence")
def test_update_with_binance(limit_short_order, limit_exit_short_order, fee, ten_minutes_ago, caplog):
    """
        10 minute short limit trade on binance

        Short trade
        fee: 0.25% base
        interest_rate: 0.05% per day
        open_rate: 0.00001173 base
        close_rate: 0.00001099 base
        amount: 90.99181073 crypto
        borrowed: 90.99181073  crypto
        time-periods: 10 minutes(rounds up to 1/24 time-period of 1 day)
        interest: borrowed * interest_rate * time-periods
                    = 90.99181073 * 0.0005 * 1/24 = 0.0018956627235416667 crypto
        open_value: (amount * open_rate) - (amount * open_rate * fee)
            = 90.99181073 * 0.00001173 - 90.99181073 * 0.00001173 * 0.0025
            = 0.0010646656050132426
        amount_closed: amount + interest = 90.99181073 + 0.0018956627235416667 = 90.99370639272354
        close_value: (amount_closed * close_rate) + (amount_closed * close_rate * fee)
            = (90.99370639272354 * 0.00001099) + (90.99370639272354 * 0.00001099 * 0.0025)
            = 0.0010025208853391716
        total_profit = open_value - close_value
            = 0.0010646656050132426 - 0.0010025208853391716
            = 0.00006214471967407108
        total_profit_percentage = (open_value/close_value) - 1
            = (0.0010646656050132426/0.0010025208853391716)-1
            = 0.06198845388946328
    """
    trade = Trade(
        id=2,
        pair='ETH/BTC',
        stake_amount=0.001,
        open_rate=0.01,
        amount=5,
        is_open=True,
        open_date=ten_minutes_ago,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        # borrowed=90.99181073,
        exchange='binance'
    )
    #assert trade.open_order_id is None
    assert trade.close_profit is None
    assert trade.close_date is None
    assert trade.borrowed is None
    assert trade.is_short is None
    #trade.open_order_id = 'something'
    trade.update(limit_short_order)
    #assert trade.open_order_id is None
    assert trade.open_rate == 0.00001173
    assert trade.close_profit is None
    assert trade.close_date is None
    assert trade.borrowed == 90.99181073
    assert trade.is_short is True
    assert log_has_re(r"LIMIT_SELL has been fulfilled for Trade\(id=2, "
                      r"pair=ETH/BTC, amount=90.99181073, open_rate=0.00001173, open_since=.*\).",
                      caplog)
    caplog.clear()
    #trade.open_order_id = 'something'
    trade.update(limit_exit_short_order)
    #assert trade.open_order_id is None
    assert trade.close_rate == 0.00001099
    assert trade.close_profit == 0.06198845
    assert trade.close_date is not None
    assert log_has_re(r"LIMIT_BUY has been fulfilled for Trade\(id=2, "
                      r"pair=ETH/BTC, amount=90.99181073, open_rate=0.00001173, open_since=.*\).",
                      caplog)


@pytest.mark.usefixtures("init_persistence")
def test_update_market_order(
    market_short_order,
    market_exit_short_order,
    fee,
    ten_minutes_ago,
    caplog
):
    """
        10 minute short market trade on Kraken at 3x leverage
        Short trade
        fee: 0.25% base
        interest_rate: 0.05% per 4 hrs
        open_rate: 0.00004173 base
        close_rate: 0.00004099 base
        amount: 91.99181073 * leverage(3) = 275.97543219 crypto
        borrowed: 275.97543219  crypto
        time-periods: 10 minutes(rounds up to 1 time-period of 4hrs)
        interest: borrowed * interest_rate * time-periods
                    = 275.97543219 * 0.0005 * 1 = 0.137987716095 crypto
        open_value: (amount * open_rate) - (amount * open_rate * fee)
            = 275.97543219 * 0.00004173 - 275.97543219 * 0.00004173 * 0.0025
            = 0.011487663648325479
        amount_closed: amount + interest = 275.97543219 + 0.137987716095 = 276.113419906095
        close_value: (amount_closed * close_rate) + (amount_closed * close_rate * fee)
            = (276.113419906095 * 0.00004099) + (276.113419906095 * 0.00004099 * 0.0025)
            = 0.01134618380465571
        total_profit = open_value - close_value
            = 0.011487663648325479 - 0.01134618380465571
            = 0.00014147984366976937
        total_profit_percentage = (open_value/close_value) - 1
        = (0.011487663648325479/0.01134618380465571)-1
        = 0.012469377026284034
    """
    trade = Trade(
        id=1,
        pair='ETH/BTC',
        stake_amount=0.001,
        amount=5,
        open_rate=0.01,
        is_open=True,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        open_date=ten_minutes_ago,
        exchange='kraken'
    )
    trade.open_order_id = 'something'
    trade.update(market_short_order)
    assert trade.leverage == 3.0
    assert trade.is_short == True
    assert trade.open_order_id is None
    assert trade.open_rate == 0.00004173
    assert trade.close_profit is None
    assert trade.close_date is None
    assert trade.interest_rate == 0.0005
    # TODO: Uncomment the next assert and make it work.
    # The logger also has the exact same but there's some spacing in there
    # assert log_has_re(r"MARKET_SELL has been fulfilled for Trade\(id=1, "
    #                   r"pair=ETH/BTC, amount=275.97543219, open_rate=0.00004173, open_since=.*\).",
    #                   caplog)
    caplog.clear()
    trade.is_open = True
    trade.open_order_id = 'something'
    trade.update(market_exit_short_order)
    assert trade.open_order_id is None
    assert trade.close_rate == 0.00004099
    assert trade.close_profit == 0.01246938
    assert trade.close_date is not None
    # TODO: The amount should maybe be the opening amount + the interest
    # TODO: Uncomment the next assert and make it work.
    # The logger also has the exact same but there's some spacing in there
    # assert log_has_re(r"MARKET_SELL has been fulfilled for Trade\(id=1, "
    #                   r"pair=ETH/BTC, amount=275.97543219, open_rate=0.00004099, open_since=.*\).",
    #                   caplog)

# TODO-mg: create a leveraged long order


@pytest.mark.usefixtures("init_persistence")
def test_calc_open_close_trade_price(limit_short_order, limit_exit_short_order, five_hours_ago, fee):
    """
        5 hour short trade on Binance
        Short trade
        fee: 0.25% base
        interest_rate: 0.05% per day
        open_rate: 0.00001173 base
        close_rate: 0.00001099 base
        amount: 90.99181073 crypto
        borrowed: 90.99181073  crypto
        time-periods: 5 hours = 5/24
        interest: borrowed * interest_rate * time-periods
                    = 90.99181073 * 0.0005 * 5/24 = 0.009478313617708333 crypto
        open_value: (amount * open_rate) - (amount * open_rate * fee)
            = 90.99181073 * 0.00001173 - 90.99181073 * 0.00001173 * 0.0025
            = 0.0010646656050132426
        amount_closed: amount + interest = 90.99181073 + 0.009478313617708333 = 91.0012890436177
        close_value: (amount_closed * close_rate) + (amount_closed * close_rate * fee)
            = (91.0012890436177 * 0.00001099) + (91.0012890436177 * 0.00001099 * 0.0025)
            = 0.001002604427005832
        total_profit = open_value - close_value
            = 0.0010646656050132426 - 0.001002604427005832
            = 0.00006206117800741065
        total_profit_percentage = (open_value/close_value) - 1
            = (0.0010646656050132426/0.0010025208853391716)-1
            = 0.06189996406932852
    """
    trade = Trade(
        pair='ETH/BTC',
        stake_amount=0.001,
        open_rate=0.01,
        amount=5,
        open_date=five_hours_ago,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        exchange='binance'
    )
    trade.open_order_id = 'something'
    trade.update(limit_short_order)
    assert trade._calc_open_trade_value() == 0.0010646656050132426
    trade.update(limit_exit_short_order)

    assert isclose(trade.calc_close_trade_value(), 0.001002604427005832)
    # Profit in BTC
    assert isclose(trade.calc_profit(), 0.00006206)
    #Profit in percent
    assert isclose(trade.calc_profit_ratio(), 0.06189996)


@pytest.mark.usefixtures("init_persistence")
def test_trade_close(fee, five_hours_ago):
    """
        Five hour short trade on Kraken at 3x leverage
        Short trade
        Exchange: Kraken
        fee: 0.25% base
        interest_rate: 0.05% per 4 hours
        open_rate: 0.02 base
        close_rate: 0.01 base
        leverage: 3.0
        amount: 5 * 3 = 15 crypto
        borrowed: 15 crypto
        time-periods: 5 hours = 5/4

        interest: borrowed * interest_rate * time-periods
                    = 15 * 0.0005 * 5/4 = 0.009375 crypto
        open_value: (amount * open_rate) - (amount * open_rate * fee)
            = (15 * 0.02) - (15 * 0.02 * 0.0025)
            = 0.29925
        amount_closed: amount + interest = 15 + 0.009375 = 15.009375
        close_value: (amount_closed * close_rate) + (amount_closed * close_rate * fee)
            = (15.009375 * 0.01) + (15.009375 * 0.01 * 0.0025)
            = 0.150468984375
        total_profit = open_value - close_value
            = 0.29925 - 0.150468984375
            = 0.148781015625
        total_profit_percentage = (open_value/close_value) - 1
            = (0.29925/0.150468984375)-1
            = 0.9887819489377738
    """
    trade = Trade(
        pair='ETH/BTC',
        stake_amount=0.001,
        open_rate=0.02,
        amount=5,
        is_open=True,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        open_date=five_hours_ago,
        exchange='kraken',
        is_short=True,
        leverage=3.0,
        interest_rate=0.0005
    )
    assert trade.close_profit is None
    assert trade.close_date is None
    assert trade.is_open is True
    trade.close(0.01)
    assert trade.is_open is False
    assert trade.close_profit == 0.98878195
    assert trade.close_date is not None

    # TODO-mg: Remove these comments probably
    #new_date = arrow.Arrow(2020, 2, 2, 15, 6, 1).datetime,
    # assert trade.close_date != new_date
    # # Close should NOT update close_date if the trade has been closed already
    # assert trade.is_open is False
    # trade.close_date = new_date
    # trade.close(0.02)
    # assert trade.close_date == new_date


@pytest.mark.usefixtures("init_persistence")
def test_calc_close_trade_price_exception(limit_short_order, fee):
    trade = Trade(
        pair='ETH/BTC',
        stake_amount=0.001,
        open_rate=0.1,
        amount=5,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        exchange='binance',
    )
    trade.open_order_id = 'something'
    trade.update(limit_short_order)
    assert trade.calc_close_trade_value() == 0.0


@pytest.mark.usefixtures("init_persistence")
def test_update_open_order(limit_short_order):
    trade = Trade(
        pair='ETH/BTC',
        stake_amount=1.00,
        open_rate=0.01,
        amount=5,
        fee_open=0.1,
        fee_close=0.1,
        exchange='binance',
    )
    assert trade.open_order_id is None
    assert trade.close_profit is None
    assert trade.close_date is None
    limit_short_order['status'] = 'open'
    trade.update(limit_short_order)
    assert trade.open_order_id is None
    assert trade.close_profit is None
    assert trade.close_date is None


@pytest.mark.usefixtures("init_persistence")
def test_calc_open_trade_value(market_short_order, fee):
    trade = Trade(
        pair='ETH/BTC',
        stake_amount=0.001,
        amount=5,
        open_rate=0.00004173,
        fee_open=fee.return_value,
        fee_close=fee.return_value,
        exchange='kraken',
    )
    trade.open_order_id = 'open_trade'
    trade.update(market_short_order)  # Buy @ 0.00001099
    # Get the open rate price with the standard fee rate
    assert trade._calc_open_trade_value() == 0.011487663648325479
    trade.fee_open = 0.003
    # Get the open rate price with a custom fee rate
    assert trade._calc_open_trade_value() == 0.011481905420932834


# @pytest.mark.usefixtures("init_persistence")
# def test_calc_close_trade_price(limit_buy_order, limit_sell_order, fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         amount=5,
#         open_rate=0.00001099,
#         fee_open=fee.return_value,
#         fee_close=fee.return_value,
#         exchange='binance',
#     )
#     trade.open_order_id = 'close_trade'
#     trade.update(limit_buy_order)  # Buy @ 0.00001099
#     # Get the close rate price with a custom close rate and a regular fee rate
#     assert trade.calc_close_trade_value(rate=0.00001234) == 0.0011200318470471794
#     # Get the close rate price with a custom close rate and a custom fee rate
#     assert trade.calc_close_trade_value(rate=0.00001234, fee=0.003) == 0.0011194704275749754
#     # Test when we apply a Sell order, and ask price with a custom fee rate
#     trade.update(limit_sell_order)
#     assert trade.calc_close_trade_value(fee=0.005) == 0.0010619972701635854


# @pytest.mark.usefixtures("init_persistence")
# def test_calc_profit(limit_buy_order, limit_sell_order, fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         amount=5,
#         open_rate=0.00001099,
#         fee_open=fee.return_value,
#         fee_close=fee.return_value,
#         exchange='binance',
#     )
#     trade.open_order_id = 'something'
#     trade.update(limit_buy_order)  # Buy @ 0.00001099
#     # Custom closing rate and regular fee rate
#     # Higher than open rate
#     assert trade.calc_profit(rate=0.00001234) == 0.00011753
#     # Lower than open rate
#     assert trade.calc_profit(rate=0.00000123) == -0.00089086
#     # Custom closing rate and custom fee rate
#     # Higher than open rate
#     assert trade.calc_profit(rate=0.00001234, fee=0.003) == 0.00011697
#     # Lower than open rate
#     assert trade.calc_profit(rate=0.00000123, fee=0.003) == -0.00089092
#     # Test when we apply a Sell order. Sell higher than open rate @ 0.00001173
#     trade.update(limit_sell_order)
#     assert trade.calc_profit() == 0.00006217
#     # Test with a custom fee rate on the close trade
#     assert trade.calc_profit(fee=0.003) == 0.00006163


# @pytest.mark.usefixtures("init_persistence")
# def test_calc_profit_ratio(limit_buy_order, limit_sell_order, fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         amount=5,
#         open_rate=0.00001099,
#         fee_open=fee.return_value,
#         fee_close=fee.return_value,
#         exchange='binance',
#     )
#     trade.open_order_id = 'something'
#     trade.update(limit_buy_order)  # Buy @ 0.00001099
#     # Get percent of profit with a custom rate (Higher than open rate)
#     assert trade.calc_profit_ratio(rate=0.00001234) == 0.11723875
#     # Get percent of profit with a custom rate (Lower than open rate)
#     assert trade.calc_profit_ratio(rate=0.00000123) == -0.88863828
#     # Test when we apply a Sell order. Sell higher than open rate @ 0.00001173
#     trade.update(limit_sell_order)
#     assert trade.calc_profit_ratio() == 0.06201058
#     # Test with a custom fee rate on the close trade
#     assert trade.calc_profit_ratio(fee=0.003) == 0.06147824
#     trade.open_trade_value = 0.0
#     assert trade.calc_profit_ratio(fee=0.003) == 0.0


# def test_adjust_stop_loss(fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         amount=5,
#         fee_open=fee.return_value,
#         fee_close=fee.return_value,
#         exchange='binance',
#         open_rate=1,
#         max_rate=1,
#     )
#     trade.adjust_stop_loss(trade.open_rate, 0.05, True)
#     assert trade.stop_loss == 0.95
#     assert trade.stop_loss_pct == -0.05
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     # Get percent of profit with a lower rate
#     trade.adjust_stop_loss(0.96, 0.05)
#     assert trade.stop_loss == 0.95
#     assert trade.stop_loss_pct == -0.05
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     # Get percent of profit with a custom rate (Higher than open rate)
#     trade.adjust_stop_loss(1.3, -0.1)
#     assert round(trade.stop_loss, 8) == 1.17
#     assert trade.stop_loss_pct == -0.1
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     # current rate lower again ... should not change
#     trade.adjust_stop_loss(1.2, 0.1)
#     assert round(trade.stop_loss, 8) == 1.17
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     # current rate higher... should raise stoploss
#     trade.adjust_stop_loss(1.4, 0.1)
#     assert round(trade.stop_loss, 8) == 1.26
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     #  Initial is true but stop_loss set - so doesn't do anything
#     trade.adjust_stop_loss(1.7, 0.1, True)
#     assert round(trade.stop_loss, 8) == 1.26
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     assert trade.stop_loss_pct == -0.1


# def test_adjust_min_max_rates(fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         amount=5,
#         fee_open=fee.return_value,
#         fee_close=fee.return_value,
#         exchange='binance',
#         open_rate=1,
#     )
#     trade.adjust_min_max_rates(trade.open_rate)
#     assert trade.max_rate == 1
#     assert trade.min_rate == 1
#     # check min adjusted, max remained
#     trade.adjust_min_max_rates(0.96)
#     assert trade.max_rate == 1
#     assert trade.min_rate == 0.96
#     # check max adjusted, min remains
#     trade.adjust_min_max_rates(1.05)
#     assert trade.max_rate == 1.05
#     assert trade.min_rate == 0.96
#     # current rate "in the middle" - no adjustment
#     trade.adjust_min_max_rates(1.03)
#     assert trade.max_rate == 1.05
#     assert trade.min_rate == 0.96


# @pytest.mark.usefixtures("init_persistence")
# @pytest.mark.parametrize('use_db', [True, False])
# def test_get_open(fee, use_db):
#     Trade.use_db = use_db
#     Trade.reset_trades()
#     create_mock_trades(fee, use_db)
#     assert len(Trade.get_open_trades()) == 4
#     Trade.use_db = True


# def test_stoploss_reinitialization(default_conf, fee):
#     init_db(default_conf['db_url'])
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         fee_open=fee.return_value,
#         open_date=arrow.utcnow().shift(hours=-2).datetime,
#         amount=10,
#         fee_close=fee.return_value,
#         exchange='binance',
#         open_rate=1,
#         max_rate=1,
#     )
#     trade.adjust_stop_loss(trade.open_rate, 0.05, True)
#     assert trade.stop_loss == 0.95
#     assert trade.stop_loss_pct == -0.05
#     assert trade.initial_stop_loss == 0.95
#     assert trade.initial_stop_loss_pct == -0.05
#     Trade.query.session.add(trade)
#     # Lower stoploss
#     Trade.stoploss_reinitialization(0.06)
#     trades = Trade.get_open_trades()
#     assert len(trades) == 1
#     trade_adj = trades[0]
#     assert trade_adj.stop_loss == 0.94
#     assert trade_adj.stop_loss_pct == -0.06
#     assert trade_adj.initial_stop_loss == 0.94
#     assert trade_adj.initial_stop_loss_pct == -0.06
#     # Raise stoploss
#     Trade.stoploss_reinitialization(0.04)
#     trades = Trade.get_open_trades()
#     assert len(trades) == 1
#     trade_adj = trades[0]
#     assert trade_adj.stop_loss == 0.96
#     assert trade_adj.stop_loss_pct == -0.04
#     assert trade_adj.initial_stop_loss == 0.96
#     assert trade_adj.initial_stop_loss_pct == -0.04
#     # Trailing stoploss (move stoplos up a bit)
#     trade.adjust_stop_loss(1.02, 0.04)
#     assert trade_adj.stop_loss == 0.9792
#     assert trade_adj.initial_stop_loss == 0.96
#     Trade.stoploss_reinitialization(0.04)
#     trades = Trade.get_open_trades()
#     assert len(trades) == 1
#     trade_adj = trades[0]
#     # Stoploss should not change in this case.
#     assert trade_adj.stop_loss == 0.9792
#     assert trade_adj.stop_loss_pct == -0.04
#     assert trade_adj.initial_stop_loss == 0.96
#     assert trade_adj.initial_stop_loss_pct == -0.04


# def test_update_fee(fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         fee_open=fee.return_value,
#         open_date=arrow.utcnow().shift(hours=-2).datetime,
#         amount=10,
#         fee_close=fee.return_value,
#         exchange='binance',
#         open_rate=1,
#         max_rate=1,
#     )
#     fee_cost = 0.15
#     fee_currency = 'BTC'
#     fee_rate = 0.0075
#     assert trade.fee_open_currency is None
#     assert not trade.fee_updated('buy')
#     assert not trade.fee_updated('sell')
#     trade.update_fee(fee_cost, fee_currency, fee_rate, 'buy')
#     assert trade.fee_updated('buy')
#     assert not trade.fee_updated('sell')
#     assert trade.fee_open_currency == fee_currency
#     assert trade.fee_open_cost == fee_cost
#     assert trade.fee_open == fee_rate
#     # Setting buy rate should "guess" close rate
#     assert trade.fee_close == fee_rate
#     assert trade.fee_close_currency is None
#     assert trade.fee_close_cost is None
#     fee_rate = 0.0076
#     trade.update_fee(fee_cost, fee_currency, fee_rate, 'sell')
#     assert trade.fee_updated('buy')
#     assert trade.fee_updated('sell')
#     assert trade.fee_close == 0.0076
#     assert trade.fee_close_cost == fee_cost
#     assert trade.fee_close == fee_rate


# def test_fee_updated(fee):
#     trade = Trade(
#         pair='ETH/BTC',
#         stake_amount=0.001,
#         fee_open=fee.return_value,
#         open_date=arrow.utcnow().shift(hours=-2).datetime,
#         amount=10,
#         fee_close=fee.return_value,
#         exchange='binance',
#         open_rate=1,
#         max_rate=1,
#     )
#     assert trade.fee_open_currency is None
#     assert not trade.fee_updated('buy')
#     assert not trade.fee_updated('sell')
#     assert not trade.fee_updated('asdf')
#     trade.update_fee(0.15, 'BTC', 0.0075, 'buy')
#     assert trade.fee_updated('buy')
#     assert not trade.fee_updated('sell')
#     assert trade.fee_open_currency is not None
#     assert trade.fee_close_currency is None
#     trade.update_fee(0.15, 'ABC', 0.0075, 'sell')
#     assert trade.fee_updated('buy')
#     assert trade.fee_updated('sell')
#     assert not trade.fee_updated('asfd')


# @pytest.mark.usefixtures("init_persistence")
# @pytest.mark.parametrize('use_db', [True, False])
# def test_total_open_trades_stakes(fee, use_db):
#     Trade.use_db = use_db
#     Trade.reset_trades()
#     res = Trade.total_open_trades_stakes()
#     assert res == 0
#     create_mock_trades(fee, use_db)
#     res = Trade.total_open_trades_stakes()
#     assert res == 0.004
#     Trade.use_db = True


# @pytest.mark.usefixtures("init_persistence")
# def test_get_overall_performance(fee):
#     create_mock_trades(fee)
#     res = Trade.get_overall_performance()
#     assert len(res) == 2
#     assert 'pair' in res[0]
#     assert 'profit' in res[0]
#     assert 'count' in res[0]


# @pytest.mark.usefixtures("init_persistence")
# def test_get_best_pair(fee):
#     res = Trade.get_best_pair()
#     assert res is None
#     create_mock_trades(fee)
#     res = Trade.get_best_pair()
#     assert len(res) == 2
#     assert res[0] == 'XRP/BTC'
#     assert res[1] == 0.01


# @pytest.mark.usefixtures("init_persistence")
# def test_update_order_from_ccxt(caplog):
#     # Most basic order return (only has orderid)
#     o = Order.parse_from_ccxt_object({'id': '1234'}, 'ETH/BTC', 'buy')
#     assert isinstance(o, Order)
#     assert o.ft_pair == 'ETH/BTC'
#     assert o.ft_order_side == 'buy'
#     assert o.order_id == '1234'
#     assert o.ft_is_open
#     ccxt_order = {
#         'id': '1234',
#         'side': 'buy',
#         'symbol': 'ETH/BTC',
#         'type': 'limit',
#         'price': 1234.5,
#         'amount':  20.0,
#         'filled': 9,
#         'remaining': 11,
#         'status': 'open',
#         'timestamp': 1599394315123
#     }
#     o = Order.parse_from_ccxt_object(ccxt_order, 'ETH/BTC', 'buy')
#     assert isinstance(o, Order)
#     assert o.ft_pair == 'ETH/BTC'
#     assert o.ft_order_side == 'buy'
#     assert o.order_id == '1234'
#     assert o.order_type == 'limit'
#     assert o.price == 1234.5
#     assert o.filled == 9
#     assert o.remaining == 11
#     assert o.order_date is not None
#     assert o.ft_is_open
#     assert o.order_filled_date is None
#     # Order has been closed
#     ccxt_order.update({'filled': 20.0, 'remaining': 0.0, 'status': 'closed'})
#     o.update_from_ccxt_object(ccxt_order)
#     assert o.filled == 20.0
#     assert o.remaining == 0.0
#     assert not o.ft_is_open
#     assert o.order_filled_date is not None
#     ccxt_order.update({'id': 'somethingelse'})
#     with pytest.raises(DependencyException, match=r"Order-id's don't match"):
#         o.update_from_ccxt_object(ccxt_order)
#     message = "aaaa is not a valid response object."
#     assert not log_has(message, caplog)
#     Order.update_orders([o], 'aaaa')
#     assert log_has(message, caplog)
#     # Call regular update - shouldn't fail.
#     Order.update_orders([o], {'id': '1234'})
