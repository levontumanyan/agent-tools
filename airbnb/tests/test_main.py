from src.main import resolve_price_filters


def test_nightly_is_scaled_by_stay_length():
	assert resolve_price_filters(20, 45, None, None, 28) == (560, 1260, "nightly")
	assert resolve_price_filters(20, 45, None, None, 3) == (60, 135, "nightly")


def test_total_passes_through_unchanged():
	assert resolve_price_filters(None, None, 100, 1600, 28) == (100, 1600, "total")
	assert resolve_price_filters(None, None, 0, 400, 28) == (0, 400, "total")


def test_one_sided_nightly_leaves_other_bound_unfiltered():
	assert resolve_price_filters(None, 45, None, None, 28) == (0, 1260, "nightly")
	assert resolve_price_filters(20, None, None, None, 28) == (560, 0, "nightly")


def test_no_price_flags_means_no_filter():
	assert resolve_price_filters(None, None, None, None, 28) == (0, 0, "total")


def test_nightly_family_takes_precedence():
	assert resolve_price_filters(20, 45, 100, 1600, 28) == (560, 1260, "nightly")
