from kronos_trading_bot.risk import evaluate_order_intent


def _paper_policy(**overrides):
    policy = {
        "mode": "paper",
        "allow_live_trading": False,
        "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
        "max_daily_loss_pct": 0.03,
        "max_single_position_pct": 0.10,
        "max_open_positions": 2,
        "pyramiding_enabled": False,
        "require_stop_loss": True,
    }
    policy.update(overrides)
    return policy


def _portfolio(**overrides):
    portfolio = {
        "equity_usdt": 10000,
        "starting_day_equity_usdt": 10000,
        "open_positions": {},
    }
    portfolio.update(overrides)
    return portfolio


def _intent(**overrides):
    intent = {
        "symbol": "BTC/USDT",
        "mode": "paper",
        "notional_usdt": 100,
        "stop_loss": 95,
    }
    intent.update(overrides)
    return intent


def test_rejects_live_mode_even_for_valid_symbol():
    # Arrange
    policy = _paper_policy(mode="live")
    intent = _intent(mode="live")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "live_trading_rejected"


def test_rejects_non_paper_mode():
    # Arrange
    policy = _paper_policy()
    intent = _intent(mode="backtest")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "non_paper_mode_rejected"


def test_rejects_failed_data_quality_before_symbol_checks():
    # Arrange
    policy = _paper_policy(allowed_symbols=["BTC/USDT"])
    intent = _intent(symbol="ETH/USDT")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=False,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "data_quality_failed"


def test_rejects_stale_model_before_symbol_checks():
    # Arrange
    policy = _paper_policy(allowed_symbols=["BTC/USDT"])
    intent = _intent(symbol="ETH/USDT")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=True,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "stale_model"


def test_rejects_unsupported_symbol():
    # Arrange
    policy = _paper_policy(allowed_symbols=["BTC/USDT"])
    intent = _intent(symbol="ETH/USDT")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "unsupported_symbol"


def test_rejects_when_daily_loss_limit_is_breached():
    # Arrange
    policy = _paper_policy(max_daily_loss_pct=0.03)
    intent = _intent(notional_usdt=100)
    portfolio = _portfolio(equity_usdt=9600, starting_day_equity_usdt=10000)

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "max_daily_loss_exceeded"


def test_rejects_when_max_open_positions_is_reached():
    # Arrange
    policy = _paper_policy(max_open_positions=2)
    intent = _intent(symbol="ETH/USDT")
    portfolio = _portfolio(open_positions={"BTC/USDT": {}, "SOL/USDT": {}})

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "max_open_positions_reached"


def test_rejects_pyramiding_when_position_already_exists():
    # Arrange
    policy = _paper_policy(max_open_positions=2, pyramiding_enabled=False)
    intent = _intent(symbol="BTC/USDT")
    portfolio = _portfolio(open_positions={"BTC/USDT": {}})

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "pyramiding_rejected"


def test_rejects_missing_required_stop_loss():
    # Arrange
    policy = _paper_policy(require_stop_loss=True)
    intent = _intent()
    intent.pop("stop_loss")
    portfolio = _portfolio()

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "missing_stop_loss"


def test_rejects_oversized_single_position():
    # Arrange
    policy = _paper_policy(max_single_position_pct=0.10)
    intent = _intent(notional_usdt=1500)
    portfolio = _portfolio(equity_usdt=10000)

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "max_single_position_exceeded"


def test_approves_valid_paper_order_intent():
    # Arrange
    policy = _paper_policy()
    intent = _intent(notional_usdt=500)
    portfolio = _portfolio(equity_usdt=10000)

    # Act
    decision = evaluate_order_intent(
        intent,
        portfolio,
        policy,
        data_quality_passed=True,
        model_is_stale=False,
    )

    # Assert
    assert decision.approved is True
    assert decision.reason_code == "approved"
    assert decision.adjusted_notional_usdt == 500
