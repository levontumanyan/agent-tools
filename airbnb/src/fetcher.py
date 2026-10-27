import json
import logging
import re
import threading
from datetime import datetime, timedelta

import pyairbnb
import pyairbnb.api
import pyairbnb.details
import pyairbnb.parse as parse
import pyairbnb.price
import pyairbnb.search
import pyairbnb.start
from curl_cffi import requests

from auth import get_brave_cookies
from config import AIRBNB_COOKIE, LISTING_CACHE

# Robustly patch pyairbnb.api.get to fallback to airbnb.ca or default key if airbnb.com redirects
_orig_pyairbnb_api_get = pyairbnb.api.get


def _robust_pyairbnb_api_get(*args, **kwargs):
	try:
		return _orig_pyairbnb_api_get(*args, **kwargs)
	except Exception:
		try:
			r = requests.get("https://www.airbnb.ca", impersonate="chrome120")
			m = re.search(r'"api_config":\{"key":"([^"]+)"', r.text)
			if m:
				return m.group(1)
		except Exception:
			pass
		return "d306zoyjsyarp7ifhu67rjxn52tv0t20"


pyairbnb.api.get = _robust_pyairbnb_api_get

# Fast-path: stub out heavy calendar & host details fetches that aren't used in scoring
pyairbnb.start.get_calendar = lambda *args, **kwargs: {}
pyairbnb.start.host_details.get = lambda *args, **kwargs: {}

_thread_local = threading.local()


def _get_session():
	if not hasattr(_thread_local, "session"):
		_thread_local.session = requests.Session(impersonate="chrome120")
	return _thread_local.session


_orig_details_get = pyairbnb.details.get
ACTIVE_COOKIES_DICT = {}


def set_session_cookie(cookie_str):
	global AIRBNB_COOKIE, ACTIVE_COOKIES_DICT
	if cookie_str:
		AIRBNB_COOKIE = cookie_str.strip()
		ACTIVE_COOKIES_DICT = dict(
			item.split("=", 1) for item in AIRBNB_COOKIE.split("; ") if "=" in item
		)


if AIRBNB_COOKIE:
	set_session_cookie(AIRBNB_COOKIE)
else:
	brave_cookies = get_brave_cookies()
	if brave_cookies:
		ACTIVE_COOKIES_DICT = brave_cookies
		AIRBNB_COOKIE = "; ".join([f"{k}={v}" for k, v in brave_cookies.items()])


def _authenticated_details_get(room_url, language, proxy_url, timeout=None, **kwargs):

	headers = {
		"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
		"Accept-Language": language,
		"Cache-Control": "no-cache",
		"Pragma": "no-cache",
		"Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
		"Sec-Ch-Ua-Mobile": "?0",
		"Sec-Ch-Ua-Platform": '"Windows"',
		"Sec-Fetch-Dest": "document",
		"Sec-Fetch-Mode": "navigate",
		"Sec-Fetch-Site": "none",
		"Sec-Fetch-User": "?1",
		"Upgrade-Insecure-Requests": "1",
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
	}
	if AIRBNB_COOKIE:
		headers["Cookie"] = AIRBNB_COOKIE
	proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
	session = _get_session()
	req_kwargs = {"headers": headers, "proxies": proxies}
	if timeout is not None:
		req_kwargs["timeout"] = timeout
	response = session.get(room_url, **req_kwargs)
	response.raise_for_status()
	data_formatted, price_dependency_input = parse.parse_body_details_wrapper(
		response.text
	)
	try:
		data_raw, _, _ = parse.parse_body_details(response.text)
		pdp = (
			data_raw.get("data", {})
			.get("presentation", {})
			.get("stayProductDetailPage", {})
			.get("sections", {})
		)
		meta = pdp.get("metadata", {})
		seo_title = (meta.get("seoFeatures") or {}).get("title") or ""
		share_title = (meta.get("sharingConfig") or {}).get("title") or ""
		if not data_formatted.get("title"):
			data_formatted["title"] = (
				seo_title.split(" - ")[0].strip() if seo_title else share_title
			)
		if share_title and not data_formatted.get("sub_description", {}).get("title"):
			data_formatted.setdefault("sub_description", {"title": "", "items": []})[
				"title"
			] = share_title
		if not data_formatted.get("description"):
			desc_parts = []
			for sec in pdp.get("sections", []) or []:
				if sec.get("sectionId") == "DESCRIPTION_MODAL":
					for it in (sec.get("section") or {}).get("items") or []:
						hdr = it.get("title")
						txt = ((it.get("html") or {}).get("htmlText") or "").strip()
						if txt:
							desc_parts.append(f"{hdr}: {txt}" if hdr else txt)
			if desc_parts:
				data_formatted["description"] = "\n\n".join(desc_parts)

		# Primary extraction for amenities from pdpPresentation
		node_amenities = (
			data_raw.get("data", {})
			.get("node", {})
			.get("pdpPresentation", {})
			.get("amenities", {})
		)
		groups_raw = (
			node_amenities.get("seeAllAmenitiesGroups")
			or node_amenities.get("previewAmenitiesGroups")
			or []
		)
		if groups_raw:
			formatted_groups = []
			for g in groups_raw:
				g_title = g.get("title") or ""
				is_not_included = "not included" in g_title.lower()
				val_list = []
				for am in g.get("amenities") or []:
					val_list.append(
						{
							"title": am.get("title") or "",
							"subtitle": am.get("subtitle") or "",
							"icon": am.get("icon") or "",
							"available": False
							if is_not_included
							else am.get("available", True),
						}
					)
				if val_list:
					formatted_groups.append(
						{
							"title": g_title,
							"values": val_list,
						}
					)
			if formatted_groups:
				data_formatted["amenities"] = formatted_groups
	except Exception:
		pass
	cookies = response.cookies
	return data_formatted, price_dependency_input, cookies


pyairbnb.details.get = _authenticated_details_get

logger = logging.getLogger("airbnb")


def get_listing_details(
	listing_id,
	currency="CAD",
	check_in=None,
	check_out=None,
	adults=1,
	force_refresh=False,
):
	"""
	Get full details for a specific listing with file-based caching.
	"""
	cache_file = LISTING_CACHE / f"{listing_id}.json"
	details = None

	# Check cache first
	if cache_file.exists() and not force_refresh:
		file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
		if datetime.now() - file_time < timedelta(hours=24):
			logger.info(f"CACHE HIT: Listing {listing_id} (last updated {file_time})")
			with open(cache_file, "r") as f:
				details = json.load(f)
			if details and not details.get("title") and not details.get("description"):
				details = None
		else:
			logger.info(f"CACHE MISS (EXPIRED): Listing {listing_id} (older than 24h)")
	else:
		logger.info(f"CACHE MISS: Listing {listing_id} not found in cache")

	# Fetch from API if not in cache or expired
	if not details:
		logger.info(f"API FETCH: Fetching listing {listing_id}...")
		import time

		max_retries = 3
		for attempt in range(max_retries):
			try:
				if attempt > 0:
					time.sleep(attempt * 1.5)
				details = pyairbnb.get_details(
					room_id=listing_id,
					domain="www.airbnb.ca",
					currency=currency,
				)

				if details:
					revs = details.get("reviews") or []
					if revs and not (details.get("host") or {}).get("name"):
						reviewee = revs[0].get("reviewee") or {}
						if reviewee.get("firstName"):
							details["host"] = {
								"id": reviewee.get("id", ""),
								"name": reviewee.get("firstName", ""),
							}
					with open(cache_file, "w") as f:
						json.dump(details, f, indent=4)
				break

			except Exception as e:
				if "429" in str(e) and attempt < max_retries - 1:
					wait_time = (attempt + 1) * 3
					logger.warning(
						f"Rate limited (429) fetching {listing_id}. Waiting {wait_time}s before retry (attempt {attempt + 1}/{max_retries})..."
					)
					time.sleep(wait_time)
					continue
				logger.error(f"Error fetching details for listing {listing_id}: {e}")
				return None

	# Fetch exact authenticated pricing if dates provided
	if details and check_in and check_out:
		try:
			import re

			d_in = datetime.strptime(check_in, "%Y-%m-%d").date()
			d_out = datetime.strptime(check_out, "%Y-%m-%d").date()
			num_days = max(1, (d_out - d_in).days)

			p_resp = pyairbnb.price.get(
				room_id=listing_id,
				check_in=d_in,
				check_out=d_out,
				adults=adults,
				currency=currency,
				api_key="d306zoyjsyarp7ifhu67rjxn52tv0t20",
				cookies=ACTIVE_COOKIES_DICT or None,
			)
			main = p_resp.get("main", {})
			p_details = main.get("details", {}) or {}
			disc_str = (
				main.get("discountedPrice")
				or main.get("price")
				or p_details.get("Price after discount")
				or p_details.get("Total")
				or ""
			)
			orig_str = main.get("originalPrice") or ""
			nights_val = None
			for k, v in p_details.items():
				if " x " in k or "nights" in k.lower():
					nights_val = v
					break

			if not orig_str and nights_val:
				orig_str = nights_val

			if not disc_str and nights_val:
				disc_str = nights_val

			if not orig_str:
				orig_str = disc_str
			if disc_str:
				m_disc = re.search(r"[\d,]+(?:\.\d+)?", disc_str.replace("\xa0", ""))
				m_orig = re.search(r"[\d,]+(?:\.\d+)?", orig_str.replace("\xa0", ""))
				tot_amt = float(m_disc.group(0).replace(",", "")) if m_disc else 0.0
				orig_amt = (
					float(m_orig.group(0).replace(",", "")) if m_orig else tot_amt
				)
				disc_pct = (
					round(((orig_amt - tot_amt) / orig_amt) * 100, 1)
					if orig_amt > tot_amt
					else 0.0
				)
				details["exact_price"] = {
					"amount": tot_amt,
					"orig_amount": orig_amt,
					"discount_pct": disc_pct,
					"nightly": round(tot_amt / num_days, 2),
					"currency": currency,
				}
		except Exception as e:
			logger.debug(f"Could not fetch exact price for {listing_id}: {e}")

	return details


def batch_get_listing_details(
	listing_ids,
	currency="CAD",
	max_workers=10,
	check_in=None,
	check_out=None,
	adults=1,
):
	"""
	Fetches details for multiple listings in parallel using a thread pool.
	Returns a dictionary mapping listing_id to details dict.
	"""
	from concurrent.futures import ThreadPoolExecutor, as_completed

	results = {}
	with ThreadPoolExecutor(max_workers=max_workers) as executor:
		future_to_id = {
			executor.submit(
				get_listing_details,
				lid,
				currency=currency,
				check_in=check_in,
				check_out=check_out,
				adults=adults,
			): str(lid)
			for lid in listing_ids
		}
		for future in as_completed(future_to_id):
			lid = future_to_id[future]
			try:
				details = future.result()
				if details:
					results[lid] = details
			except Exception as e:
				logger.error(f"Failed to fetch {lid} in batch: {e}")
	return results


def search_listings(
	location_coords,
	check_in,
	check_out,
	min_price=0,
	max_price=1000,
	currency="CAD",
	place_type=None,
	amenities=None,
	language="en",
	free_cancellation=False,
	zoom_value=15,
	adults=1,
):
	"""
	Search for Airbnb listings within a bounding box using pyairbnb.search_all.
	"""

	logger.info(
		f"Searching for {place_type or 'all types'} ({adults} adults) in {currency} between {check_in} and {check_out} (range {min_price}-{max_price})..."
	)

	try:
		results = pyairbnb.search_all(
			check_in=check_in,
			check_out=check_out,
			ne_lat=location_coords["ne_lat"],
			ne_long=location_coords["ne_long"],
			sw_lat=location_coords["sw_lat"],
			sw_long=location_coords["sw_long"],
			zoom_value=zoom_value,
			price_min=min_price,
			price_max=max_price,
			currency=currency,
			place_type=place_type,
			amenities=amenities,
			language=language,
			free_cancellation=free_cancellation,
			adults=adults,
		)
		logger.debug(f"API returned {len(results)} results")
		return results

	except Exception as e:
		logger.error(f"Error fetching listings: {e}")
		return []


if __name__ == "__main__":
	# Setup minimal logging for internal test
	logging.basicConfig(level=logging.INFO)
	# Simple test for Montreal area
	montreal_coords = {
		"ne_lat": 45.52,
		"ne_long": -73.55,
		"sw_lat": 45.50,
		"sw_long": -73.57,
	}

	listings = search_listings(montreal_coords, "2026-10-03", "2026-10-31")
	logger.info(f"Found {len(listings)} listings.")

	if listings:
		first = listings[0]
		first_id = first.get("room_id")
		logger.info(f"Fetching details for the first listing: {first_id}")
		details = get_listing_details(first_id)
		if details:
			logger.info(f"Name: {details.get('title')}")
			logger.info(f"Reviews: {len(details.get('reviews', []))} found in details")
