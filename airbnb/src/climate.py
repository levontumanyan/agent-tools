import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

try:
	from config import CLIMATE_CACHE
except ImportError:
	CLIMATE_CACHE = Path(__file__).parent.parent / ".cache" / "climate.json"

logger = logging.getLogger("airbnb")

_MEMORY_CLIMATE_CACHE: Dict[str, Dict[str, Any]] = {}


def _load_disk_cache() -> Dict[str, Dict[str, Any]]:
	if not CLIMATE_CACHE.exists():
		return {}
	try:
		with open(CLIMATE_CACHE, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception as e:
		logger.warning(f"Failed to read climate cache: {e}")
		return {}


def _save_disk_cache(cache: Dict[str, Dict[str, Any]]) -> None:
	try:
		CLIMATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
		with open(CLIMATE_CACHE, "w", encoding="utf-8") as f:
			json.dump(cache, f, indent=4)
	except Exception as e:
		logger.warning(f"Failed to write climate cache: {e}")


def get_climate_profile(
	lat: float,
	lon: float,
	check_in: Optional[str] = None,
	check_out: Optional[str] = None,
) -> Dict[str, Any]:
	"""
	Fetches climate normals (expected daily min and max temperatures) for the target location
	and calendar window using Open-Meteo's historical archive API.

	Results are cached by rounded coordinates (~1km resolution) and calendar window.
	"""
	now = datetime.now()
	if check_in:
		try:
			d1 = datetime.strptime(check_in, "%Y-%m-%d")
		except ValueError:
			d1 = now
	else:
		d1 = now

	if check_out:
		try:
			d2 = datetime.strptime(check_out, "%Y-%m-%d")
		except ValueError:
			d2 = d1 + timedelta(days=28)
	else:
		d2 = d1 + timedelta(days=28)

	# Use historical records from a completed reference year
	hist_year = 2023
	day_clamped = min(d1.day, 28)
	start_dt = datetime(hist_year, d1.month, day_clamped)
	stay_days = max(1, (d2 - d1).days)
	end_dt = start_dt + timedelta(days=stay_days)

	start_date_str = start_dt.strftime("%Y-%m-%d")
	end_date_str = end_dt.strftime("%Y-%m-%d")

	cache_key = f"{round(lat, 2):.2f}_{round(lon, 2):.2f}_{start_dt.strftime('%m%d')}_{end_dt.strftime('%m%d')}"

	# 1. Check in-memory cache
	if cache_key in _MEMORY_CLIMATE_CACHE:
		return _MEMORY_CLIMATE_CACHE[cache_key]

	# 2. Check disk cache
	disk_cache = _load_disk_cache()
	if cache_key in disk_cache:
		_MEMORY_CLIMATE_CACHE[cache_key] = disk_cache[cache_key]
		return disk_cache[cache_key]

	# 3. Query Open-Meteo archive API
	params = {
		"latitude": round(lat, 4),
		"longitude": round(lon, 4),
		"start_date": start_date_str,
		"end_date": end_date_str,
		"daily": "temperature_2m_max,temperature_2m_min",
		"timezone": "auto",
	}
	url = f"https://archive-api.open-meteo.com/v1/archive?{urllib.parse.urlencode(params)}"

	try:
		req = urllib.request.Request(
			url,
			headers={"User-Agent": "AirbnbCLI-ClimateEngine/1.0"},
		)
		with urllib.request.urlopen(req, timeout=5) as resp:
			data = json.loads(resp.read().decode("utf-8"))

		daily = data.get("daily", {})
		tmax_list = [t for t in daily.get("temperature_2m_max", []) if t is not None]
		tmin_list = [t for t in daily.get("temperature_2m_min", []) if t is not None]

		if not tmax_list or not tmin_list:
			raise ValueError("Empty temperature data received from Open-Meteo")

		avg_max = round(sum(tmax_list) / len(tmax_list), 1)
		avg_min = round(sum(tmin_list) / len(tmin_list), 1)

		# Decision thresholds
		ac_needed = avg_max >= 26.5
		heating_needed = avg_min <= 13.0

		if ac_needed and heating_needed:
			summary = f"Extreme Diurnal Swing ({avg_min}°C – {avg_max}°C)"
		elif ac_needed:
			summary = f"Warm/Hot Climate ({avg_min}°C – {avg_max}°C)"
		elif heating_needed:
			summary = f"Cool/Chilly Climate ({avg_min}°C – {avg_max}°C)"
		else:
			summary = f"Mild/Temperate Climate ({avg_min}°C – {avg_max}°C)"

		result = {
			"avg_max_temp": avg_max,
			"avg_min_temp": avg_min,
			"ac_needed": ac_needed,
			"heating_needed": heating_needed,
			"summary": summary,
			"source": "open-meteo",
		}

		# Store cache
		_MEMORY_CLIMATE_CACHE[cache_key] = result
		disk_cache[cache_key] = result
		_save_disk_cache(disk_cache)
		logger.info(f"Climate profile for ({lat:.2f}, {lon:.2f}): {summary}")
		return result

	except Exception as e:
		logger.warning(
			f"Could not fetch climate data for ({lat:.2f}, {lon:.2f}): {e}. Using fallback."
		)
		fallback = {
			"avg_max_temp": None,
			"avg_min_temp": None,
			"ac_needed": True,  # Fallback to requiring AC if unknown
			"heating_needed": False,
			"summary": "Unknown Climate (Fallback)",
			"source": "fallback",
		}
		_MEMORY_CLIMATE_CACHE[cache_key] = fallback
		return fallback
