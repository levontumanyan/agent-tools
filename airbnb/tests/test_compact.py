from src.main import _format_coords, compact_listing


def test_compact_listing_drops_verbose_fields_and_keeps_coordinates():
	listing = {
		"rank": 1,
		"score": 82.5,
		"id": "12345",
		"name": "Sunny Studio",
		"nightly_price": 45.0,
		"total_price": 1260.0,
		"currency": "CAD",
		"coordinates": {"latitude": 11.2524, "longitude": -85.8689},
		"review_evidence": {"wifi_positive": ["Great wifi!"] * 10},
		"description": "Long listing description",
		"reviews": [{"comments": "Nice place"}],
		"reviews_matched": 1,
		"url": "https://www.airbnb.ca/rooms/12345",
	}

	compacted = compact_listing(listing)

	assert compacted["id"] == "12345"
	assert compacted["coordinates"] == {"latitude": 11.2524, "longitude": -85.8689}
	assert compacted["nightly_price"] == 45.0
	assert compacted["url"] == "https://www.airbnb.ca/rooms/12345"
	assert "review_evidence" not in compacted
	assert "description" not in compacted
	assert "reviews" not in compacted
	assert "reviews_matched" not in compacted


def test_format_coords():
	assert (
		_format_coords({"latitude": 11.25241, "longitude": -85.86892})
		== "11.2524, -85.8689"
	)
	assert _format_coords({}) == "-"
	assert _format_coords(None) == "-"
