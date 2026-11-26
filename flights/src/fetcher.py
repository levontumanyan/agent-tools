import json
import logging
from datetime import datetime, timedelta

from config import CACHE_TTL_HOURS, FLIGHTS_CACHE_DIR
from models import FlightItinerary, FlightSearchQuery
from providers import get_provider

logger = logging.getLogger("flights")


def fetch_flights(
	query: FlightSearchQuery, force_refresh: bool = False
) -> list[FlightItinerary]:
	"""Fetches flight itineraries from provider or local cache if fresh."""
	cache_file = FLIGHTS_CACHE_DIR / f"{query.cache_key}.json"

	# Check local disk cache
	if cache_file.exists() and not force_refresh:
		file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
		age = datetime.now() - file_mtime
		if age < timedelta(hours=CACHE_TTL_HOURS):
			logger.info(
				f"CACHE HIT: {query.cache_key} (cached {int(age.total_seconds() / 60)} mins ago)"
			)
			try:
				with open(cache_file, "r", encoding="utf-8") as f:
					data = json.load(f)
					return [FlightItinerary.from_dict(d) for d in data]
			except Exception as e:
				logger.warning(
					f"Failed to read cache file {cache_file}: {e}. Refetching..."
				)
		else:
			logger.info(
				f"CACHE EXPIRED: {query.cache_key} (older than {CACHE_TTL_HOURS} hours)"
			)
	else:
		logger.info(f"CACHE MISS: {query.cache_key}")

	# Query the provider
	provider = get_provider(query.provider)
	itineraries = provider.search(query)

	if itineraries:
		try:
			with open(cache_file, "w", encoding="utf-8") as f:
				json.dump([it.to_dict() for it in itineraries], f, indent="\t")
			logger.info(f"Cached {len(itineraries)} itineraries to {cache_file.name}")
		except Exception as e:
			logger.warning(f"Failed to save cache file {cache_file}: {e}")

	return itineraries
