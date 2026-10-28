import json

from src.fetcher import get_listing_details, search_listings


def test_get_listing_details_cache_hit(mocker, tmp_path):
	"""Verify details are loaded from cache if fresh (within 24 hours)."""
	listing_id = "12345"
	mock_details = {"title": "Cached Listing", "room_id": listing_id}

	# Mock cache path
	mock_listing_cache_dir = tmp_path / "listings"
	mock_listing_cache_dir.mkdir()
	mock_cache_file = mock_listing_cache_dir / f"{listing_id}.json"

	with open(mock_cache_file, "w") as f:
		json.dump(mock_details, f)

	mocker.patch("src.fetcher.LISTING_CACHE", mock_listing_cache_dir)
	mock_pyairbnb = mocker.patch("src.fetcher.pyairbnb")

	details = get_listing_details(listing_id)

	assert details == mock_details
	mock_pyairbnb.get_details.assert_not_called()


def test_get_listing_details_cache_expired(mocker, tmp_path):
	"""Verify API is called if cache is older than 24 hours."""
	listing_id = "12345"
	old_details = {"title": "Old Listing"}
	new_details = {"title": "New Listing", "room_id": listing_id}

	mock_listing_cache_dir = tmp_path / "listings"
	mock_listing_cache_dir.mkdir()
	mock_cache_file = mock_listing_cache_dir / f"{listing_id}.json"

	# Write old data
	with open(mock_cache_file, "w") as f:
		json.dump(old_details, f)

	# Manually set file modification time to 2 days ago
	import os
	import time

	past_time = time.time() - (48 * 3600)
	os.utime(mock_cache_file, (past_time, past_time))

	mocker.patch("src.fetcher.LISTING_CACHE", mock_listing_cache_dir)
	mock_pyairbnb = mocker.patch("src.fetcher.pyairbnb")
	mock_pyairbnb.get_details.return_value = new_details

	details = get_listing_details(listing_id)

	assert details == new_details
	mock_pyairbnb.get_details.assert_called_once()


def test_search_listings_params(mocker):
	"""Verify search_listings passes correct parameters to pyairbnb."""
	mock_pyairbnb = mocker.patch("src.fetcher.pyairbnb")
	coords = {"ne_lat": 1, "ne_long": 2, "sw_lat": 3, "sw_long": 4}

	search_listings(
		coords,
		check_in="2026-10-03",
		check_out="2026-10-31",
		min_price=100,
		max_price=200,
	)
	# Verify coordinates and price range were passed
	args, kwargs = mock_pyairbnb.search_all.call_args
	assert kwargs["ne_lat"] == 1
	assert kwargs["ne_long"] == 2
	assert kwargs["price_min"] == 100
	assert kwargs["price_max"] == 200


def test_get_listing_calendar(mocker):
	"""Verify get_listing_calendar executes GraphQL query and returns calendar months."""
	mock_session = mocker.MagicMock()
	mock_response = mocker.MagicMock()
	mock_response.json.return_value = {
		"data": {
			"merlin": {
				"pdpAvailabilityCalendar": {
					"calendarMonths": [
						{
							"month": 11,
							"year": 2026,
							"days": [
								{"calendarDate": "2026-11-01", "available": False},
								{"calendarDate": "2026-11-02", "available": True},
							],
						}
					]
				}
			}
		}
	}
	mock_session.get.return_value = mock_response
	mocker.patch("src.fetcher._get_session", return_value=mock_session)
	mocker.patch("src.fetcher._robust_pyairbnb_api_get", return_value="dummy_key")

	from src.fetcher import get_listing_calendar

	months = get_listing_calendar("12345", month=11, year=2026, count=1)
	assert len(months) == 1
	assert months[0]["month"] == 11
	assert len(months[0]["days"]) == 2
	assert months[0]["days"][1]["available"] is True
	mock_session.get.assert_called_once()

