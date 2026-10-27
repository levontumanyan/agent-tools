import json
import logging
import sys
import urllib.request

from geopy.geocoders import Nominatim

from config import (
	AMENITIES_PATH,
	BENCHMARKS_PATH,
	CITY_CACHE,
	LOG_FILE,
	SEARCH_FILTERS_PATH,
)

logger = logging.getLogger("airbnb")


def setup_logging(level=logging.WARNING, stream=sys.stdout):
	"""
	Configures logging to both console and file.
	"""
	# Clear existing handlers
	if logger.hasHandlers():
		logger.handlers.clear()

	logger.setLevel(logging.DEBUG)  # Capture everything, filter at handlers
	formatter = logging.Formatter(
		"%(asctime)s - %(name)s - %(levelname)s - %(message)s"
	)

	# Console Handler
	console_handler = logging.StreamHandler(stream)
	console_handler.setLevel(level)
	console_handler.setFormatter(formatter)
	logger.addHandler(console_handler)

	# File Handler
	file_handler = logging.FileHandler(LOG_FILE)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)
	logger.addHandler(file_handler)

	return logger


def load_amenity_map():
	"""
	Loads amenity mappings from amenities.json and flattens them.
	"""
	if not AMENITIES_PATH.exists():
		return {}

	with open(AMENITIES_PATH, "r") as f:
		try:
			data = json.load(f)
			# Flatten categories into a single dict
			flat_map = {}
			for category in data.values():
				flat_map.update(category)
			return flat_map
		except json.JSONDecodeError:
			return {}


def load_benchmarks():
	"""
	Loads benchmarks from benchmarks.json.
	"""
	if not BENCHMARKS_PATH.exists():
		return {}

	with open(BENCHMARKS_PATH, "r") as f:
		try:
			return json.load(f)
		except json.JSONDecodeError:
			return {}


def load_search_filters():
	"""
	Loads search filters from search_filters.json.
	"""
	if not SEARCH_FILTERS_PATH.exists():
		return {"defaults": {}, "amenity_ids": {}}

	with open(SEARCH_FILTERS_PATH, "r") as f:
		try:
			return json.load(f)
		except json.JSONDecodeError:
			return {"defaults": {}, "amenity_ids": {}}


def get_city_coords(city_name):
	"""
	Gets the bounding box for a city, with caching.
	Returns a dict with ne_lat, ne_long, sw_lat, sw_long.
	"""

	# Try to load from cache
	cache = {}
	if CITY_CACHE.exists():
		with open(CITY_CACHE, "r") as f:
			try:
				cache = json.load(f)
			except json.JSONDecodeError:
				pass

	if city_name in cache:
		logger.debug(f"City cache hit for {city_name}")
		return cache[city_name]

	# Fetch from geopy if not cached
	logger.info(f"Geocoding {city_name}...")
	geolocator = Nominatim(user_agent="airbnb-benchmarker")
	location = geolocator.geocode(city_name, exactly_one=True)

	if not location:
		logger.error(f"Failed to geocode city: {city_name}")
		return None

	# Nominatim returns raw data including boundingbox: [lat_min, lat_max, lon_min, lon_max]
	raw_bbox = location.raw.get("boundingbox")
	if not raw_bbox:
		# Fallback if boundingbox is not provided: use center point + small offset
		lat, lon = location.latitude, location.longitude
		coords = {
			"sw_lat": lat - 0.02,
			"sw_long": lon - 0.02,
			"ne_lat": lat + 0.02,
			"ne_long": lon + 0.02,
		}
	else:
		# Nominatim order: [sw_lat, ne_lat, sw_lon, ne_lon]
		sw_lat = float(raw_bbox[0])
		ne_lat = float(raw_bbox[1])
		sw_long = float(raw_bbox[2])
		ne_long = float(raw_bbox[3])

		# If bounding box is too tiny (e.g. single building/point < 0.04 deg ~ 4.4km), expand to minimum useful radius
		min_span = 0.04
		if (ne_lat - sw_lat) < min_span:
			mid_lat = (ne_lat + sw_lat) / 2
			sw_lat = mid_lat - min_span / 2
			ne_lat = mid_lat + min_span / 2
		if (ne_long - sw_long) < min_span:
			mid_long = (ne_long + sw_long) / 2
			sw_long = mid_long - min_span / 2
			ne_long = mid_long + min_span / 2

		coords = {
			"sw_lat": sw_lat,
			"ne_lat": ne_lat,
			"sw_long": sw_long,
			"ne_long": ne_long,
		}

	# Save to cache
	cache[city_name] = coords

	with open(CITY_CACHE, "w") as f:
		json.dump(cache, f, indent=4)

	return coords


def check_internet_connection(host="http://google.com"):
	"""
	Quickly checks if there is an active internet connection.
	"""
	try:
		urllib.request.urlopen(host, timeout=3)
		return True
	except Exception:
		return False
