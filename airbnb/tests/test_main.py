from src.main import resolve_price_filters


def test_explicit_total_is_never_scaled():
	assert resolve_price_filters(0, 400, 28, "total") == (0, 400, "total")
	assert resolve_price_filters(100, 1600, 28, "total") == (100, 1600, "total")
	assert resolve_price_filters(100, 1600, 2, "total") == (100, 1600, "total")


def test_explicit_nightly_is_always_scaled():
	assert resolve_price_filters(20, 45, 28, "nightly") == (560, 1260, "nightly")
	assert resolve_price_filters(20, 45, 3, "nightly") == (60, 135, "nightly")


def test_auto_detects_nightly_on_long_stays():
	assert resolve_price_filters(20, 45, 28, "auto") == (560, 1260, "nightly")


def test_auto_treats_large_prices_as_total():
	assert resolve_price_filters(700, 1600, 28, "auto") == (700, 1600, "total")


def test_auto_treats_short_stays_as_total():
	assert resolve_price_filters(20, 45, 7, "auto") == (20, 45, "total")
	assert resolve_price_filters(20, 45, 5, "auto") == (20, 45, "total")
