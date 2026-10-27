import json

from src.utils import get_city_coords


def test_get_city_coords_from_cache(mocker, tmp_path):
	"""Verify coordinates are loaded from cache if present."""
	# Create a mock cache file
	mock_cache_dir = tmp_path / ".cache"
	mock_cache_dir.mkdir()
	mock_city_cache = mock_cache_dir / "cities.json"

	city_data = {
		"Montreal": {"sw_lat": 45.0, "ne_lat": 46.0, "sw_long": -74.0, "ne_long": -73.0}
	}
	with open(mock_city_cache, "w") as f:
		json.dump(city_data, f)

	# Mock the CITY_CACHE path in utils.py
	mocker.patch("src.utils.CITY_CACHE", mock_city_cache)

	# Also mock Nominatim just in case it's called (it shouldn't be)
	mock_geo = mocker.patch("src.utils.Nominatim")

	coords = get_city_coords("Montreal")

	assert coords == city_data["Montreal"]
	mock_geo.assert_not_called()


def test_get_city_coords_geocoding_success(mocker, tmp_path):
	"""Verify coordinates are fetched via geocoding when not in cache."""
	# Mock empty cache
	mock_city_cache = tmp_path / "cities.json"
	mocker.patch("src.utils.CITY_CACHE", mock_city_cache)

	# Mock Nominatim geocoder
	mock_location = mocker.Mock()
	mock_location.latitude = 45.5
	mock_location.longitude = -73.5
	mock_location.raw = {"boundingbox": ["45.0", "46.0", "-74.0", "-73.0"]}

	mock_geolocator = mocker.Mock()
	mock_geolocator.geocode.return_value = mock_location
	mocker.patch("src.utils.Nominatim", return_value=mock_geolocator)

	coords = get_city_coords("Montreal")

	assert coords["sw_lat"] == 45.0
	assert coords["ne_lat"] == 46.0
	assert coords["sw_long"] == -74.0
	assert coords["ne_long"] == -73.0

	# Verify it was saved to cache
	with open(mock_city_cache, "r") as f:
		cache_data = json.load(f)
		assert "Montreal" in cache_data
