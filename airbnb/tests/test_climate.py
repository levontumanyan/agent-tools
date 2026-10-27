import json
from unittest.mock import MagicMock, patch

from src.climate import get_climate_profile


def test_get_climate_profile_mocked():
	mock_response_data = {
		"daily": {
			"temperature_2m_max": [24.0, 25.0, 24.5],
			"temperature_2m_min": [10.0, 11.0, 10.5],
		}
	}

	with (
		patch("src.climate._load_disk_cache", return_value={}),
		patch("src.climate._save_disk_cache"),
		patch("src.climate._MEMORY_CLIMATE_CACHE", {}),
		patch("urllib.request.urlopen") as mock_urlopen,
	):
		mock_resp = MagicMock()
		mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
		mock_resp.__enter__.return_value = mock_resp
		mock_urlopen.return_value = mock_resp

		profile = get_climate_profile(
			-16.40, -71.53, check_in="2026-11-11", check_out="2026-12-09"
		)

		assert profile["avg_max_temp"] == 24.5
		assert profile["avg_min_temp"] == 10.5
		assert profile["ac_needed"] is False
		assert profile["heating_needed"] is True
		assert "Cool/Chilly" in profile["summary"]


def test_get_climate_profile_hot_climate():
	mock_response_data = {
		"daily": {
			"temperature_2m_max": [29.0, 30.0, 28.5],
			"temperature_2m_min": [22.0, 23.0, 21.5],
		}
	}

	with (
		patch("src.climate._load_disk_cache", return_value={}),
		patch("src.climate._save_disk_cache"),
		patch("src.climate._MEMORY_CLIMATE_CACHE", {}),
		patch("urllib.request.urlopen") as mock_urlopen,
	):
		mock_resp = MagicMock()
		mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
		mock_resp.__enter__.return_value = mock_resp
		mock_urlopen.return_value = mock_resp

		profile = get_climate_profile(
			-12.12, -77.01, check_in="2026-02-01", check_out="2026-02-28"
		)

		assert profile["avg_max_temp"] == 29.2
		assert profile["avg_min_temp"] == 22.2
		assert profile["ac_needed"] is True
		assert profile["heating_needed"] is False
		assert "Warm/Hot" in profile["summary"]


def test_get_climate_profile_network_fallback():
	with (
		patch("src.climate._load_disk_cache", return_value={}),
		patch("src.climate._save_disk_cache"),
		patch("src.climate._MEMORY_CLIMATE_CACHE", {}),
		patch("urllib.request.urlopen", side_effect=Exception("Timeout")),
	):
		profile = get_climate_profile(
			88.12, -177.01, check_in="2026-06-01", check_out="2026-06-15"
		)
		assert profile["source"] == "fallback"
		assert profile["ac_needed"] is True
