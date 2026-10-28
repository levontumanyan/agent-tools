import argparse
import json
import logging
import re
import statistics
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from amenities import get_search_id
from config import REPORTS_DIR
from fetcher import search_listings
from reporter import (
	generate_csv_report,
	generate_json_report,
	generate_survey_report,
)
from scorer import Scorer
from utils import (
	check_internet_connection,
	get_city_coords,
	load_amenity_map,
	load_benchmarks,
	load_search_filters,
	setup_logging,
)


def run_survey(args, defaults, search_amenities, logger):
	delimiter = ";" if ";" in args.cities else ","
	raw_cities = [c.strip() for c in args.cities.split(delimiter) if c.strip()]
	if not raw_cities:
		logger.error("No cities provided for survey.")
		return

	d1 = datetime.strptime(args.check_in, "%Y-%m-%d")
	d2 = datetime.strptime(args.check_out, "%Y-%m-%d")
	num_nights = max(1, (d2 - d1).days)

	survey_results = []
	if not args.json:
		print(
			f"\nStarting market price survey across {len(raw_cities)} cities for {args.check_in} to {args.check_out} ({num_nights} nights, {args.currency})...\n"
		)

	for city in raw_cities:
		logger.info(f"Surveying {city}...")
		coords = get_city_coords(city)
		if not coords:
			logger.warning(f"Could not resolve coords for {city}, skipping.")
			continue

		listings = search_listings(
			coords,
			check_in=args.check_in,
			check_out=args.check_out,
			min_price=0,
			max_price=10000,
			currency=args.currency,
			place_type=args.place_type,
			amenities=search_amenities if search_amenities else None,
			language=defaults.get("language", "en"),
			free_cancellation=defaults.get("free_cancellation", False),
			zoom_value=defaults.get("zoom_value", 12),
		)

		prices = []
		discounts = []
		qualified_prices = []

		for item in listings:
			p_info = item.get("price", {})
			unit = p_info.get("unit", {})
			amt = (
				unit.get("discount")
				or unit.get("amount")
				or p_info.get("total", {}).get("amount", 0)
			)
			orig_amt = unit.get("amount") or amt

			try:
				amt_float = float(amt)
				orig_float = float(orig_amt)
			except (ValueError, TypeError):
				continue

			if amt_float > 0:
				prices.append(amt_float)
				if orig_float > amt_float:
					discounts.append(((orig_float - amt_float) / orig_float) * 100)

				val = float(item.get("rating", {}).get("value", 0) or 0)
				try:
					rc = int(item.get("rating", {}).get("reviewCount", 0) or 0)
				except (ValueError, TypeError):
					rc = 0

				if val >= args.min_rating and rc >= args.min_reviews:
					qualified_prices.append(amt_float)

		# Calculate stay duration
		d1 = datetime.strptime(args.check_in, "%Y-%m-%d")
		d2 = datetime.strptime(args.check_out, "%Y-%m-%d")
		num_nights = max(1, (d2 - d1).days)

		target_list = qualified_prices if qualified_prices else prices
		if target_list:
			med = round(statistics.median(target_list), 2)
			mean_val = round(statistics.mean(target_list), 2)
			p25 = (
				round(statistics.quantiles(target_list, n=4)[0], 2)
				if len(target_list) >= 4
				else round(min(target_list), 2)
			)
			p75 = (
				round(statistics.quantiles(target_list, n=4)[2], 2)
				if len(target_list) >= 4
				else round(max(target_list), 2)
			)
			nightly_med = round(med / num_nights, 2)
			avg_disc = round(statistics.mean(discounts), 1) if discounts else 0.0
			pct_disc = round((len(discounts) / len(prices)) * 100, 1) if prices else 0.0

			res = {
				"city": city,
				"total_found": len(listings),
				"qualified_count": len(qualified_prices),
				"median_total": med,
				"mean_total": mean_val,
				"nightly_median": nightly_med,
				"p25_total": p25,
				"p75_total": p75,
				"avg_monthly_discount_pct": avg_disc,
				"pct_with_discount": pct_disc,
				"currency": args.currency,
			}
			survey_results.append(res)
			if not args.json:
				print(
					f"  {city:<28} | Qualified ({args.min_rating}+): {len(qualified_prices):>3}/{len(listings):<3} | Median: {args.currency} ${med:.2f} (~${nightly_med:.2f}/nt) | Avg Discount: {avg_disc:.1f}%"
				)

	csv_path = REPORTS_DIR / f"survey-{args.check_in}-{args.check_out}.csv"
	json_path = REPORTS_DIR / f"survey-{args.check_in}-{args.check_out}.json"
	generate_survey_report(survey_results, csv_path=csv_path, json_path=json_path)

	if args.json:
		print(
			json.dumps(
				{
					"check_in": args.check_in,
					"check_out": args.check_out,
					"currency": args.currency,
					"min_rating": args.min_rating,
					"min_reviews": args.min_reviews,
					"results": survey_results,
					"csv_report": str(csv_path),
					"json_report": str(json_path),
				},
				indent=2,
			)
		)
	else:
		print(f"\nSurvey reports saved to:\n  CSV:  {csv_path}\n  JSON: {json_path}")


def main():
	# Initial parser to check for verbose and json flags before logging setup
	temp_parser = argparse.ArgumentParser(add_help=False)
	temp_parser.add_argument("-v", "--verbose", action="store_true")
	temp_parser.add_argument("--json", action="store_true")
	temp_args, _ = temp_parser.parse_known_args()

	# Configure logging (redirect to stderr when --json is used so stdout stays clean)
	log_level = logging.INFO if temp_args.verbose else logging.WARNING
	log_stream = sys.stderr if temp_args.json else sys.stdout
	logger = setup_logging(level=log_level, stream=log_stream)

	if not check_internet_connection():
		logger.error("No internet connection detected. Please check your network.")
		if temp_args.json:
			print(json.dumps({"error": "No internet connection detected."}))
		sys.exit(1)

	# Load search defaults
	filters = load_search_filters()
	defaults = filters.get("defaults", {})

	# Load amenity mappings (flattened)
	amenity_map = load_amenity_map()

	# Load benchmarks to get "must_haves"
	benchmarks = load_benchmarks()
	must_haves = benchmarks.get("hard_filters", {}).get("must_have_amenities", [])

	# Map human-readable must_haves to pyairbnb IDs
	search_amenities = []
	for amenity in must_haves:
		sid = get_search_id(amenity) or amenity_map.get(amenity)
		if sid:
			search_amenities.append(sid)

	parser = argparse.ArgumentParser(
		description="Airbnb Benchmarker - Search and Score Listings"
	)
	parser.add_argument(
		"--location",
		type=str,
		default="Montreal",
		help="Location name (e.g., 'Montreal', 'New York')",
	)
	parser.add_argument("--min_price", type=int, default=0, help="Minimum price")
	parser.add_argument("--max_price", type=int, default=500, help="Maximum price")
	parser.add_argument(
		"--check_in",
		type=str,
		default=defaults.get("check_in"),
		help="Check-in date (YYYY-MM-DD)",
	)
	parser.add_argument(
		"--check_out",
		type=str,
		default=defaults.get("check_out"),
		help="Check-out date (YYYY-MM-DD)",
	)
	parser.add_argument(
		"--place_type",
		type=str,
		default=defaults.get("place_type"),
		help="Type of place (e.g., 'Entire home/apt', 'Private room')",
	)
	parser.add_argument(
		"--currency",
		type=str,
		default=defaults.get("currency", "USD"),
		help="Currency code (e.g., 'USD', 'MXN')",
	)
	parser.add_argument(
		"--limit",
		type=int,
		default=None,
		help="Limit the number of listings to fetch and score",
	)
	parser.add_argument(
		"--fast_wifi",
		"--fast-wifi",
		action="store_true",
		help="Filter listings requiring verified Fast Wi-Fi (badges, fiber declarations, or review speed tests)",
	)
	parser.add_argument(
		"--neighborhood",
		type=str,
		default=None,
		help="Filter listings by target neighborhoods (comma-separated, e.g. 'Cayma, Yanahuara')",
	)
	parser.add_argument(
		"--max_guests",
		type=int,
		default=None,
		help="Filter listings allowing at most this many guests (e.g. 2 for solo/couples)",
	)

	parser.add_argument(
		"--survey",
		action="store_true",
		help="Run a high-level market price survey across multiple cities without fetching full details",
	)
	parser.add_argument(
		"--cities",
		type=str,
		default="Buenos Aires, Argentina; Guadalajara, Mexico; Córdoba, Argentina; Arequipa, Peru",
		help="Semicolon- or comma-separated list of cities to sweep when running in --survey mode",
	)
	parser.add_argument(
		"--min_rating",
		type=float,
		default=4.7,
		help="Minimum rating threshold for pre-filtering (default: 4.7)",
	)
	parser.add_argument(
		"--min_reviews",
		type=int,
		default=10,
		help="Minimum review count for pre-filtering (default: 10)",
	)
	parser.add_argument(
		"--no_prefilter",
		action="store_true",
		help="Disable pre-filtering by rating and review count before fetching details",
	)
	parser.add_argument(
		"-v", "--verbose", action="store_true", help="Increase output verbosity"
	)
	parser.add_argument(
		"--json",
		action="store_true",
		help="Output JSON summary directly to stdout and suppress human-readable logging",
	)
	parser.add_argument(
		"--cookie",
		type=str,
		default=None,
		help="Airbnb session cookie string to unlock authenticated discounts",
	)
	parser.add_argument(
		"--room",
		type=str,
		default=None,
		help="Inspect a single listing by room ID or Airbnb URL (e.g. '1207650713743808384' or 'https://www.airbnb.ca/rooms/1207650713743808384')",
	)
	parser.add_argument(
		"--reviews",
		action="store_true",
		help="Display full guest reviews when inspecting a listing with --room",
	)
	parser.add_argument(
		"--search_reviews",
		"--search-reviews",
		type=str,
		default=None,
		help="Filter guest reviews by keyword or regex (implies --reviews)",
	)
	parser.add_argument(
		"--calendar",
		"--cal",
		action="store_true",
		help="Display availability calendar for a listing (requires --room)",
	)
	parser.add_argument(
		"--calendar_months",
		"--calendar-months",
		type=int,
		default=3,
		help="Number of months to display for availability calendar (default: 3)",
	)

	args = parser.parse_args()

	if args.cookie:
		from fetcher import set_session_cookie

		set_session_cookie(args.cookie)

	if args.room:
		from fetcher import get_listing_details

		m_room = re.search(r"(?:rooms/)?(\d{6,})", str(args.room))
		room_id = m_room.group(1) if m_room else str(args.room).strip()

		dates_specified = any(arg in sys.argv for arg in ["--check_in", "--check-in"])
		raw_room_str = str(args.room)
		if "?" in raw_room_str:
			parsed_url = urlparse(raw_room_str)
			qp = parse_qs(parsed_url.query)
			if "check_in" in qp and not dates_specified:
				args.check_in = qp["check_in"][0]
				dates_specified = True
			if "check_out" in qp and not any(
				arg in sys.argv for arg in ["--check_out", "--check-out"]
			):
				args.check_out = qp["check_out"][0]
			if "adults" in qp and not any(
				arg in sys.argv for arg in ["--max_guests", "--max-guests"]
			):
				try:
					args.max_guests = int(qp["adults"][0])
				except (ValueError, TypeError):
					pass

		# If dates were not explicitly passed via CLI or URL, check recent reports for room_id
		if not dates_specified and REPORTS_DIR.exists():
			json_reports = sorted(
				REPORTS_DIR.glob("*.json"),
				key=lambda p: p.stat().st_mtime,
				reverse=True,
			)
			for rpath in json_reports[:10]:
				try:
					with open(rpath, "r", encoding="utf-8") as f:
						rdata = json.load(f)
					if isinstance(rdata, list):
						matched = next(
							(item for item in rdata if str(item.get("id")) == room_id),
							None,
						)
						if matched and matched.get("url"):
							m_parsed = urlparse(matched["url"])
							mqp = parse_qs(m_parsed.query)
							if "check_in" in mqp and "check_out" in mqp:
								args.check_in = mqp["check_in"][0]
								args.check_out = mqp["check_out"][0]
								dates_specified = True
								if "adults" in mqp and not any(
									arg in sys.argv
									for arg in ["--max_guests", "--max-guests"]
								):
									try:
										args.max_guests = int(mqp["adults"][0])
									except (ValueError, TypeError):
										pass
								break
				except Exception:
					pass

		d1 = datetime.strptime(args.check_in, "%Y-%m-%d")
		d2 = datetime.strptime(args.check_out, "%Y-%m-%d")
		num_nights = max(1, (d2 - d1).days)

		details = get_listing_details(
			room_id,
			currency=args.currency,
			check_in=args.check_in,
			check_out=args.check_out,
			adults=args.max_guests or 1,
		)
		if not details:
			logger.error(f"Failed to fetch details for room {room_id}")
			if args.json:
				print(
					json.dumps({"error": f"Failed to fetch details for room {room_id}"})
				)
			sys.exit(1)

		scorer = Scorer(
			benchmarks,
			num_nights=num_nights,
			require_fast_wifi=args.fast_wifi,
			check_in=args.check_in,
			check_out=args.check_out,
		)
		lp = details.get(
			"exact_price",
			{
				"amount": 0,
				"orig_amount": 0,
				"discount_pct": 0.0,
				"nightly": 0,
				"currency": args.currency,
			},
		)
		details["price"] = lp
		wifi_info = scorer.detect_fast_wifi(details)
		review_evidence = scorer.extract_review_evidence(details)
		score, penalties = scorer.calculate_score(details)

		raw_reviews = details.get("reviews", []) or []
		filtered_reviews = []
		pattern = (
			re.compile(args.search_reviews, re.IGNORECASE)
			if args.search_reviews
			else None
		)
		for r in raw_reviews:
			comment = (r.get("comments") or "").replace("<br/>", "\n").strip()
			if pattern and not pattern.search(comment):
				continue
			filtered_reviews.append(
				{
					"author": r.get("reviewer", {}).get("firstName")
					or r.get("reviewer", {}).get("first_name", "Guest"),
					"date": (r.get("createdAt") or r.get("created_at") or "")[:10]
					or r.get("localizedDate", ""),
					"rating": r.get("rating"),
					"comment": comment,
				}
			)

		rating = details.get("rating", {})
		raw_title = details.get("title")
		title_str = (
			raw_title
			if isinstance(raw_title, str) and raw_title.strip()
			else f"Room {room_id}"
		)
		sub_title = (details.get("sub_description") or {}).get("title") or details.get(
			"room_type", ""
		)
		adults_count = args.max_guests or 1
		if dates_specified and args.check_in and args.check_out:
			room_url = f"https://www.airbnb.ca/rooms/{room_id}?check_in={args.check_in}&check_out={args.check_out}&adults={adults_count}"
		else:
			room_url = f"https://www.airbnb.ca/rooms/{room_id}"
		host_info = details.get("host") or {}
		coords = details.get("coordinates") or {}
		desc_text = (details.get("description") or "").strip()

		cal_data = None
		if args.calendar:
			from fetcher import get_listing_calendar

			start_month = None
			start_year = None
			if args.check_in:
				try:
					dt_ci = datetime.strptime(args.check_in, "%Y-%m-%d")
					start_month = dt_ci.month
					start_year = dt_ci.year
				except Exception:
					pass

			cal_data = get_listing_calendar(
				room_id,
				month=start_month,
				year=start_year,
				count=args.calendar_months,
				currency=args.currency,
			)

		payload = {
			"id": room_id,
			"name": title_str,
			"summary": sub_title,
			"url": room_url,
			"score": score,
			"rating": rating,
			"review_count": rating.get("review_count", len(raw_reviews)),
			"person_capacity": details.get("person_capacity", 2),
			"is_super_host": details.get("is_super_host", False),
			"host": host_info,
			"co_hosts": details.get("co_hosts", []),
			"coordinates": coords,
			"price": lp,
			"nightly_price": lp.get("nightly", 0),
			"fast_wifi": wifi_info,
			"description": desc_text,
			"review_evidence": review_evidence,
			"penalties": penalties,
			"reviews_matched": len(filtered_reviews),
			"reviews": filtered_reviews
			if (args.reviews or args.search_reviews)
			else [],
			"calendar": cal_data if args.calendar else None,
		}

		if args.json:
			print(json.dumps(payload, indent=2, ensure_ascii=False))
		else:
			print(f"\n# {title_str}")
			if sub_title:
				print(f"Summary:     {sub_title}")
			print(f"URL:         {room_url}")
			host_label = host_info.get("name") or "Unknown"
			if details.get("is_super_host"):
				host_label += " (Superhost)"
			print(
				f"Host:        {host_label} | Max Guests: {payload['person_capacity']}"
			)
			if coords.get("latitude") or coords.get("longitude"):
				print(
					f"Coordinates: {coords.get('latitude')}, {coords.get('longitude')}"
				)
			if scorer.last_climate and scorer.last_climate.get("summary"):
				print(f"Climate:     {scorer.last_climate['summary']}")
			if lp.get("amount") or lp.get("nightly"):
				disc_part = (
					f", {lp['discount_pct']}% discount"
					if lp.get("discount_pct")
					else ""
				)
				dates_part = (
					f" for {args.check_in} -> {args.check_out}"
					if args.check_in and args.check_out
					else ""
				)
				print(
					f"Price:       {lp['currency']} ${lp['amount']:.2f} total (${lp['nightly']:.2f}/nt{disc_part}{dates_part})"
				)

			print("\n## Score & Ratings")
			score_note = (
				" (Price excluded: single listing inspect)"
				if scorer.market_median_price is None
				else ""
			)
			print(
				f"Overall Score: {score}/100{score_note} | Guest Rating: ★ {rating.get('guest_satisfaction', 0)} ({payload['review_count']} reviews)"
			)
			sub_ratings = [
				f"Cleanliness {rating.get('cleanliness')}"
				if rating.get("cleanliness")
				else None,
				f"Accuracy {rating.get('accuracy')}"
				if rating.get("accuracy")
				else None,
				f"Check-in {rating.get('checking')}"
				if rating.get("checking")
				else None,
				f"Communication {rating.get('communication')}"
				if rating.get("communication")
				else None,
				f"Location {rating.get('location')}"
				if rating.get("location")
				else None,
				f"Value {rating.get('value')}" if rating.get("value") else None,
			]
			sub_ratings_str = " | ".join(x for x in sub_ratings if x)
			if sub_ratings_str:
				print(f"Breakdown:     {sub_ratings_str}")
			if penalties:
				penalties_str = ", ".join(str(p) for p in penalties)
				print(f"Penalties:     {penalties_str}")
			flags = getattr(scorer, "last_flags", [])
			if flags:
				print(f"Flags:         {' '.join(flags)}")

			print("\n## Connectivity & Wi-Fi")
			wifi_status = (
				"Verified Fast Wi-Fi"
				if wifi_info.get("verified")
				else "Standard / Unverified"
			)
			speed_str = (
				f" ({wifi_info['speed_mbps']} Mbps)"
				if wifi_info.get("speed_mbps")
				else ""
			)
			print(
				f"Status:        {wifi_status}{speed_str} — {wifi_info.get('details', '')}"
			)

			if desc_text:
				print("\n## Listing Description")
				print(desc_text)

			has_evidence = any(v for v in review_evidence.values())
			if has_evidence:
				print("\n## Review Signals")
				for cat, quotes in review_evidence.items():
					if quotes:
						label = cat.replace("_", " ").title()
						print(f'- {label} ({len(quotes)}): "{quotes[0]}"')

			if args.reviews or args.search_reviews:
				hdr = (
					f"\n## Reviews Matching '{args.search_reviews}' ({len(filtered_reviews)}/{len(raw_reviews)})"
					if args.search_reviews
					else f"\n## All Reviews ({len(filtered_reviews)})"
				)
				print(hdr)
				for idx, rev in enumerate(filtered_reviews, 1):
					meta = " | ".join(
						str(x)
						for x in [
							rev.get("author"),
							rev.get("date"),
							f"★{rev['rating']}" if rev.get("rating") else None,
						]
						if x
					)
					print(f"{idx}. [{meta}] {rev['comment']}")
			if args.calendar and cal_data:
				from reporter import format_calendar_view

				print("\n## Availability Calendar")
				print(format_calendar_view(cal_data))
			elif not (args.reviews or args.search_reviews):
				print(
					f'\n(Tip: pass --calendar to view availability, --reviews to list all {len(raw_reviews)} reviews)'
				)
		return

	if args.survey:
		run_survey(args, defaults, search_amenities, logger)
		return

	coords = get_city_coords(args.location)
	if not coords:
		logger.error(f"Failed to find coordinates for location: {args.location}")
		if args.json:
			print(
				json.dumps(
					{
						"error": f"Failed to find coordinates for location: {args.location}"
					}
				)
			)
		sys.exit(1)

	logger.debug(f"Search Coords: {coords}")
	logger.debug(f"Search Amenities (IDs): {search_amenities}")

	# Calculate number of nights for daily price calculation
	d1 = datetime.strptime(args.check_in, "%Y-%m-%d")
	d2 = datetime.strptime(args.check_out, "%Y-%m-%d")
	num_nights = max(1, (d2 - d1).days)

	# If max_price is small (e.g. <= 500) and stay is longer than 7 nights,
	# it represents a nightly rate, so scale to total stay price for Airbnb's API filter
	if num_nights > 7 and args.max_price <= 500:
		api_min_price = args.min_price * num_nights
		api_max_price = args.max_price * num_nights
		logger.info(
			f"Detected nightly rate range ({args.min_price}-{args.max_price}/night). Scaling to total reservation price for {num_nights} nights: {api_min_price}-{api_max_price} {args.currency}"
		)
	else:
		api_min_price = args.min_price
		api_max_price = args.max_price

	logger.info(
		f"--- Searching in {args.location} (Price: {api_min_price}-{api_max_price} {args.currency}) ---"
	)

	listings = search_listings(
		coords,
		check_in=args.check_in,
		check_out=args.check_out,
		min_price=api_min_price,
		max_price=api_max_price,
		currency=args.currency,
		place_type=args.place_type,
		amenities=search_amenities if search_amenities else None,
		language=defaults.get("language", "en"),
		free_cancellation=defaults.get("free_cancellation", False),
		zoom_value=defaults.get("zoom_value", 15),
		adults=args.max_guests or 1,
	)

	logger.info(f"Found {len(listings)} total listings.")

	# Deduplicate listings by room_id
	seen_ids = set()
	unique_listings = []
	for item in listings:
		rid = str(item.get("room_id"))
		if rid not in seen_ids:
			seen_ids.add(rid)
			unique_listings.append(item)
	listings = unique_listings

	# Calculate dynamic regional market median nightly rate from RAW search results (unbiased by rating or limits)
	raw_nightly_rates = []
	for item in unique_listings:
		p_info = item.get("price", {})
		unit = p_info.get("unit", {})
		qualifier = unit.get("qualifier", "")
		amt = (
			unit.get("discount")
			or unit.get("amount")
			or p_info.get("total", {}).get("amount", 0)
		)
		try:
			amt_val = float(amt)
			if amt_val > 0:
				rate = (
					amt_val
					if ("night" in qualifier and "for" not in qualifier)
					else (amt_val / num_nights if num_nights > 0 else amt_val)
				)
				raw_nightly_rates.append(rate)
		except (ValueError, TypeError):
			continue

	market_median = (
		round(statistics.median(raw_nightly_rates), 2)
		if len(raw_nightly_rates) >= 8
		else None
	)
	if market_median and not args.json:
		logger.info(
			f"Regional market median: {market_median} {args.currency}/night (unbiased baseline across {len(raw_nightly_rates)} raw listings)"
		)
	elif len(raw_nightly_rates) < 8 and not args.json:
		logger.info(
			f"Sample size too small ({len(raw_nightly_rates)} < 8) for dynamic median; price ratio scoring omitted."
		)

	# Filter by neighborhood keywords if specified
	if args.neighborhood:
		targets = [n.strip().lower() for n in args.neighborhood.split(",") if n.strip()]
		filtered = []
		for item in listings:
			text = f"{item.get('name', '')} {item.get('title', '')}".lower()
			if any(t in text for t in targets):
				filtered.append(item)
		logger.info(
			f"Neighborhood filter '{args.neighborhood}' matched {len(filtered)}/{len(listings)} listings."
		)
		listings = filtered

	# Pre-filter by rating & reviews (default >= 4.7 rating and >= 10 reviews)
	if not args.no_prefilter:
		filtered = []
		for item in listings:
			val = float(item.get("rating", {}).get("value", 0) or 0)
			try:
				rc = int(item.get("rating", {}).get("reviewCount", 0) or 0)
			except (ValueError, TypeError):
				rc = 0
			if val >= args.min_rating and rc >= args.min_reviews:
				filtered.append(item)
		logger.info(
			f"Pre-filter (rating >= {args.min_rating}, reviews >= {args.min_reviews}) kept {len(filtered)}/{len(listings)} listings."
		)
		filtered.sort(
			key=lambda x: (
				float(x.get("rating", {}).get("value", 0) or 0),
				int(x.get("rating", {}).get("reviewCount", 0) or 0),
			),
			reverse=True,
		)
		listings = filtered

	if args.limit and not args.max_guests:
		logger.info(f"Limiting to first {args.limit} listings.")
		listings = listings[: args.limit]
	elif args.limit and args.max_guests:
		candidate_limit = max(args.limit * 3, 30)
		listings = listings[:candidate_limit]

	# Store price data from search results since details API might not return it
	listing_prices = {}
	for listing in listings:
		room_id = str(listing.get("room_id"))
		price_info = listing.get("price", {})
		unit = price_info.get("unit", {})
		qualifier = unit.get("qualifier", "")
		amt = (
			unit.get("discount")
			or unit.get("amount")
			or price_info.get("total", {}).get("amount", 0)
		)
		orig_amt = unit.get("amount") or amt

		try:
			amt_float = float(amt)
		except (ValueError, TypeError):
			amt_float = 0.0

		try:
			orig_float = float(orig_amt)
		except (ValueError, TypeError):
			orig_float = amt_float

		discount_pct = (
			round(((orig_float - amt_float) / orig_float) * 100, 1)
			if orig_float > amt_float
			else 0.0
		)

		if "night" in qualifier and "for" not in qualifier:
			nightly_rate = amt_float
			total_amt = nightly_rate * num_nights
			orig_total = orig_float * num_nights
		else:
			total_amt = amt_float
			orig_total = orig_float
			nightly_rate = total_amt / num_nights if num_nights > 0 else total_amt

		currency = unit.get("curency_symbol", args.currency)
		if " " in currency:
			currency = currency.split(" ")[-1].strip()
		if "\xa0" in currency:
			currency = currency.split("\xa0")[-1].strip()

		listing_prices[room_id] = {
			"amount": total_amt,
			"orig_amount": orig_total,
			"discount_pct": discount_pct,
			"nightly": round(nightly_rate, 2),
			"currency": currency,
		}

	# Fetch details in parallel (cached after first run)
	scorer = Scorer(
		benchmarks,
		num_nights=num_nights,
		require_fast_wifi=args.fast_wifi,
		market_median_price=market_median,
		check_in=args.check_in,
		check_out=args.check_out,
	)
	scored_results = []

	listing_ids = [str(item.get("room_id")) for item in listings]
	if not args.json:
		print(f"\nFetching and scoring {len(listing_ids)} listings in parallel...")

	from fetcher import batch_get_listing_details

	all_details = batch_get_listing_details(
		listing_ids,
		currency=args.currency,
		max_workers=10,
		check_in=args.check_in,
		check_out=args.check_out,
		adults=args.max_guests or 1,
	)

	for listing in listings:
		listing_id = str(listing.get("room_id"))
		name = listing.get("name")
		details = all_details.get(listing_id)

		if details:
			person_cap = int(details.get("person_capacity", 2) or 2)
			if args.max_guests and person_cap > args.max_guests:
				logger.debug(
					f"  Skipping {listing_id}: capacity {person_cap} exceeds max_guests {args.max_guests}"
				)
				continue

			raw_title = details.get("title")
			listing_name = (
				raw_title if isinstance(raw_title, str) and raw_title.strip() else name
			)
			rating = details.get("rating", {})
			total_amenities = sum(
				len(cat.get("values", [])) for cat in details.get("amenities", [])
			)

			lp = details.get("exact_price") or listing_prices.get(
				listing_id,
				{
					"amount": 0,
					"orig_amount": 0,
					"discount_pct": 0.0,
					"nightly": 0,
					"currency": args.currency,
				},
			)
			details["price"] = lp

			wifi_info = scorer.detect_fast_wifi(details)
			review_evidence = scorer.extract_review_evidence(details)

			score, penalties = scorer.calculate_score(details)
			adults_count = args.max_guests or 1
			room_url = (
				f"https://www.airbnb.ca/rooms/{listing_id}?check_in={args.check_in}&check_out={args.check_out}&adults={adults_count}"
				if args.check_in and args.check_out
				else f"https://www.airbnb.ca/rooms/{listing_id}"
			)

			scored_results.append(
				{
					"score": score,
					"id": listing_id,
					"name": listing_name,
					"price": lp["nightly"],
					"nightly_price": lp["nightly"],
					"total_price": lp["amount"],
					"orig_total_price": lp.get("orig_amount", lp["amount"]),
					"orig_price": lp.get("orig_amount", lp["amount"]),
					"discount_pct": lp.get("discount_pct", 0.0),
					"currency": lp["currency"],
					"bedrooms": details.get("bedrooms", 1),
					"person_capacity": details.get("person_capacity", 2),
					"review_count": rating.get("review_count", 0),
					"rating": rating.get("guest_satisfaction", 0),
					"amenities": total_amenities,
					"penalties": penalties,
					"flags": getattr(scorer, "last_flags", []),
					"kitchen_tier": getattr(scorer, "last_kitchen_tier", None),
					"fast_wifi": wifi_info,
					"review_evidence": review_evidence,
					"url": room_url,
				}
			)
			if args.limit and len(scored_results) >= args.limit:
				break
		else:
			logger.error(f"  Failed to fetch details for {listing_id}")

	# Sort results and generate report
	if scored_results:
		safe_location = re.sub(r"[ ,/]+", "-", args.location).strip("-")
		csv_filename = f"{safe_location}-{args.check_in}-{args.check_out}.csv"
		json_filename = f"{safe_location}-{args.check_in}-{args.check_out}.json"
		csv_path = REPORTS_DIR / csv_filename
		json_path = REPORTS_DIR / json_filename

		csv_ok = generate_csv_report(
			scored_results,
			csv_path,
			location=args.location,
			check_in=args.check_in,
			check_out=args.check_out,
			max_guests=args.max_guests,
			adults=args.max_guests or 1,
		)
		json_ok = generate_json_report(
			scored_results,
			json_path,
			check_in=args.check_in,
			check_out=args.check_out,
			max_guests=args.max_guests,
			adults=args.max_guests or 1,
		)

		if not (csv_ok and json_ok):
			logger.error("Failed to generate one or more report files.")
			if args.json:
				print(json.dumps({"error": "Failed to generate report files."}))
			sys.exit(1)

		if args.json:
			try:
				with open(json_path, "r", encoding="utf-8") as f:
					final_listings = json.load(f)
			except Exception:
				final_listings = scored_results

			output_payload = {
				"location": args.location,
				"check_in": args.check_in,
				"check_out": args.check_out,
				"csv_report": str(csv_path),
				"json_report": str(json_path),
				"total_listings": len(final_listings),
				"listings": final_listings,
			}
			print(json.dumps(output_payload, indent=2))
		else:
			from reporter import _format_date_human

			print(f"\nLocation: {args.location}")
			human_range = f"{_format_date_human(args.check_in)} to {_format_date_human(args.check_out)}"
			print(f"Date Range: {human_range}")
			sorted_display = sorted(
				scored_results, key=lambda x: x.get("score", 0), reverse=True
			)
			print(f"\nTop {min(10, len(sorted_display))} Scored Listings:")
			print(
				f"{'Rank':<5} {'Score':<7} {'Nightly':<14} {'Total Stay':<14} {'Rating':<8} {'Title'}"
			)
			print("-" * 80)
			for i, r in enumerate(sorted_display[:10]):
				n_price = f"{r.get('currency', '')} ${r.get('nightly_price', 0):.2f}/nt"
				t_price = f"{r.get('currency', '')} ${r.get('total_price', 0):.2f}"
				rating_str = f"★ {r.get('rating', 0):.2f}"
				title = (r.get("name") or "")[:35]
				print(
					f"#{i + 1:<4} {r.get('score', 0):<7.1f} {n_price:<14} {t_price:<14} {rating_str:<8} {title}"
				)
			print("\n--- SUCCESS: Reports saved/merged ---")
			print(f"CSV:  {csv_path}")
			print(f"JSON: {json_path}")

	else:
		if args.json:
			print(
				json.dumps(
					{
						"location": args.location,
						"check_in": args.check_in,
						"check_out": args.check_out,
						"total_listings": 0,
						"listings": [],
					},
					indent=2,
				)
			)
		else:
			print("\n--- NO RESULTS: No listings were successfully scored ---")


if __name__ == "__main__":
	main()
