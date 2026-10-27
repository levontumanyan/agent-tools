import json
import shutil

import pytest

from src.config import TEST_DATA_DIR, TEST_LISTING_ID
from src.fetcher import get_listing_details

# Path to the real listing JSON we copied for testing
TEST_LISTING_FILE = TEST_DATA_DIR / f"{TEST_LISTING_ID}.json"


@pytest.fixture
def mock_cache_env(mocker, tmp_path):
	"""
	Sets up a temporary cache environment and copies the test listing into it.
	"""
	# Create a temporary listings cache directory
	temp_cache_dir = tmp_path / "listings"
	temp_cache_dir.mkdir(parents=True, exist_ok=True)

	# Copy the real test listing JSON into the temporary cache
	shutil.copy(TEST_LISTING_FILE, temp_cache_dir / f"{TEST_LISTING_ID}.json")

	# Mock LISTING_CACHE in fetcher.py to point to our temporary directory
	mocker.patch("src.fetcher.LISTING_CACHE", temp_cache_dir)

	return temp_cache_dir


def test_get_listing_details_uses_cache_not_network(mocker, mock_cache_env):
	"""
	Verify that get_listing_details loads data from the cache and
	does NOT trigger a network call via pyairbnb.get_details.
	"""
	# Mock pyairbnb to ensure no network calls are made
	mock_pyairbnb = mocker.patch("src.fetcher.pyairbnb")

	# Load the original test data for comparison
	with open(TEST_LISTING_FILE, "r") as f:
		expected_data = json.load(f)

	# Call the function - it should find the file in our mock_cache_env
	details = get_listing_details(TEST_LISTING_ID)

	# Assertions
	assert details == expected_data, (
		"The returned details should match the cached JSON."
	)
	assert not mock_pyairbnb.get_details.called, (
		"pyairbnb.get_details should NOT have been called (Cache Hit)."
	)


def test_get_listing_details_calls_network_when_cache_missing(mocker, tmp_path):
	"""
	Verify that get_listing_details calls the network when the cache file is missing.
	"""
	# Create an empty temporary listings cache directory
	empty_cache_dir = tmp_path / "empty_listings"
	empty_cache_dir.mkdir(parents=True, exist_ok=True)

	# Mock LISTING_CACHE
	mocker.patch("src.fetcher.LISTING_CACHE", empty_cache_dir)

	# Mock pyairbnb.get_details to return a dummy listing
	mock_details = {"room_id": "999", "title": "New Listing"}
	mock_pyairbnb = mocker.patch("src.fetcher.pyairbnb")
	mock_pyairbnb.get_details.return_value = mock_details

	# Call the function with a non-existent ID
	details = get_listing_details("999")

	# Assertions
	assert details == mock_details
	assert mock_pyairbnb.get_details.called, (
		"pyairbnb.get_details SHOULD have been called (Cache Miss)."
	)

	# Verify it was saved to the cache
	cached_file = empty_cache_dir / "999.json"
	assert cached_file.exists(), "New listing should have been saved to cache."
