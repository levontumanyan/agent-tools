import re
from collections import Counter

_VISITOR_RESTRICTION_RE = re.compile(
	r"\b(?:"
	+ "|".join(
		[
			r"no visitors?",
			r"visitors? (?:are )?not allowed",
			r"no unregistered guests?",
			r"only registered guests?",
			r"registered guests? only",
			r"no outside guests?",
			r"no overnight guests?",
			r"no se permiten visitas",
			r"sin visitas",
			r"prohibid[oa]s? (?:las )?visitas",
			r"solo hu[eé]spedes registrados",
			r"s[oó]lo hu[eé]spedes registrados",
			r"[uú]nicamente hu[eé]spedes registrados",
		]
	)
	+ r")\b",
	re.IGNORECASE,
)

_PRAISE_THEMES = [
	(
		"Responsive / helpful host",
		re.compile(
			r"\b(responsive|helpful|kind|attentive|accommodating|great host|amazing host|friendly|amable|atent[oa]|servicial|excelente anfitri[oó]n)\b",
			re.IGNORECASE,
		),
	),
	(
		"Cleanliness",
		re.compile(
			r"\b(clean|spotless|immaculate|tidy|neat|limpi[oa]|impecable)\b",
			re.IGNORECASE,
		),
	),
	(
		"Comfortable / well-equipped",
		re.compile(
			r"\b(comfortable|cozy|well[- ]equipped|modern|as described|like the photos|c[oó]mod[oa]|equipad[oa]|tal cual)\b",
			re.IGNORECASE,
		),
	),
	(
		"Security & self check-in",
		re.compile(
			r"\b(safe|secure|security|self check[- ]?in|easy check[- ]?in|segur[oa]|seguridad)\b",
			re.IGNORECASE,
		),
	),
	(
		"Location & convenience",
		re.compile(
			r"\b(great location|good location|central|convenient|walkable|ubicaci[oó]n|c[eé]ntric[oa])\b",
			re.IGNORECASE,
		),
	),
	(
		"Long stays & remote work",
		re.compile(
			r"\b(long stay|extended stay|month|weeks|remote work|work from|fast wifi|good wifi|estancia larga|mes|semanas)\b",
			re.IGNORECASE,
		),
	),
]

_ISSUE_THEMES = [
	(
		"Power / electricity outages",
		re.compile(
			r"\b(power outage|no power|electricity|blackout|outage|apag[oó]n|sin luz|se fue la luz|energ[ií]a)\b",
			re.IGNORECASE,
		),
	),
	(
		"Wi-Fi / internet instability",
		re.compile(
			r"\b(slow wifi|bad wifi|poor wifi|wifi (?:was |is )?(?:unstable|spotty|down|out|weak|disconnected)|internet (?:was |is )?(?:unstable|spotty|down|out|slow)|no (?:wifi|internet)|sin internet|wifi lento|internet se cortaba)\b",
			re.IGNORECASE,
		),
	),
	(
		"Noise / construction",
		re.compile(
			r"\b(noise|noisy|loud|construction|ruido|ruidos[oa]|bulla|construcci[oó]n|obras)\b",
			re.IGNORECASE,
		),
	),
	(
		"Cleanliness / maintenance / pests",
		re.compile(
			r"\b(dirty|smell|odor|roach|cockroach|bug|insect|mold|broken|leak|no hot water|cold water|sucio|mal olor|cucaracha|humedad)\b",
			re.IGNORECASE,
		),
	),
	(
		"Space / layout / stairs",
		re.compile(
			r"\b(small|tiny|tight|cramped|awkward|narrow|steep stairs|peque[nñ][oa]|estrecho)\b",
			re.IGNORECASE,
		),
	),
]


def extract_review_text(review):
	"""Return the preferred English/localized review comment text with HTML breaks cleaned."""
	localized = review.get("localizedReview")
	text = localized.get("comments") if isinstance(localized, dict) else None
	if not text:
		text = review.get("comments") or ""
	return str(text).replace("<br/>", " ").replace("<br>", " ").strip()


def detect_visitor_restriction(details):
	"""Inspect listing house_rules for explicit visitor bans or registered-guest-only policies."""
	house_rules = details.get("house_rules") or {}
	candidates = []
	for key in ("aditional", "additional"):
		val = house_rules.get(key)
		if isinstance(val, str) and val.strip():
			candidates.extend(line.strip() for line in val.splitlines() if line.strip())

	for section in house_rules.get("general") or []:
		if not isinstance(section, dict):
			continue
		for item in section.get("values") or []:
			if isinstance(item, dict) and item.get("title"):
				candidates.append(str(item["title"]).strip())

	for text in candidates:
		if _VISITOR_RESTRICTION_RE.search(text):
			return True, text
	return False, None


def _build_listing_url(listing_id, check_in=None, check_out=None, adults=1):
	base = f"https://www.airbnb.ca/rooms/{listing_id}"
	if check_in and check_out:
		return f"{base}?check_in={check_in}&check_out={check_out}&adults={adults}"
	return base


def _extract_themes(reviews, theme_specs):
	results = []
	for name, pattern in theme_specs:
		matched_texts = []
		for rev in reviews:
			text = rev.get("text") or ""
			if text and pattern.search(text):
				matched_texts.append(text)
		if matched_texts:
			sample = matched_texts[0]
			if len(sample) > 140:
				sample = sample[:137].rstrip() + "..."
			results.append(
				{
					"theme": name,
					"count": len(matched_texts),
					"sample": sample,
				}
			)
	results.sort(key=lambda x: x["count"], reverse=True)
	return results


def analyze_host_reviews(
	host_id,
	host_name,
	host_listings_meta,
	details_by_id,
	check_in=None,
	check_out=None,
	adults=1,
	currency="CAD",
):
	"""Aggregate per-listing details and all guest reviews for a host."""
	listings_out = []
	all_reviews = []
	rating_counts = Counter()
	expected_total_reviews = 0
	is_superhost = False

	for meta in host_listings_meta:
		lid = str(meta.get("id") or "")
		if not lid:
			continue
		details = details_by_id.get(lid) or {}
		if meta.get("isSuperhost") or details.get("is_super_host"):
			is_superhost = True

		if not host_name:
			host_name = (details.get("host") or {}).get("name") or host_name

		raw_title = (
			meta.get("nameOrPlaceholderName") or details.get("title") or f"Room {lid}"
		)
		title = str(raw_title).strip()

		raw_rc = meta.get("reviewCount")
		if raw_rc is None:
			raw_rc = (details.get("rating") or {}).get("review_count")
		try:
			expected_rc = int(raw_rc or 0)
		except (ValueError, TypeError):
			expected_rc = 0
		expected_total_reviews += expected_rc

		raw_reviews = details.get("reviews") or []
		listing_rating = meta.get("ratingAverage")
		if listing_rating is None:
			listing_rating = (details.get("rating") or {}).get("guest_satisfaction")

		visitor_restricted, visitor_rule = detect_visitor_restriction(details)
		flags = ["[FLAG: Visitors Restricted]"] if visitor_restricted else []

		exact_price = details.get("exact_price")
		price_info = None
		if isinstance(exact_price, dict) and exact_price.get("amount"):
			price_info = {
				"amount": exact_price["amount"],
				"nightly": exact_price.get("nightly", 0),
				"orig_amount": exact_price.get("orig_amount", exact_price["amount"]),
				"discount_pct": exact_price.get("discount_pct", 0.0),
				"currency": exact_price.get("currency", currency),
			}

		listings_out.append(
			{
				"id": lid,
				"title": title,
				"url": _build_listing_url(
					lid, check_in=check_in, check_out=check_out, adults=adults
				),
				"room_type": meta.get("localizedRoomType")
				or details.get("room_type")
				or "",
				"person_capacity": details.get("person_capacity"),
				"rating": listing_rating,
				"expected_review_count": expected_rc,
				"fetched_review_count": len(raw_reviews),
				"price": price_info,
				"visitor_restricted": visitor_restricted,
				"visitor_rule": visitor_rule,
				"flags": flags,
				"coordinates": details.get("coordinates") or {},
			}
		)

		for r in raw_reviews:
			rating_val = r.get("rating")
			if isinstance(rating_val, (int, float)):
				rating_counts[int(round(rating_val))] += 1
			created_at = (r.get("createdAt") or r.get("created_at") or "")[:10]
			reviewer = r.get("reviewer") or {}
			author = reviewer.get("firstName") or reviewer.get("first_name") or "Guest"
			all_reviews.append(
				{
					"listing_id": lid,
					"listing_title": title,
					"author": author,
					"rating": rating_val,
					"created_at": created_at,
					"localized_date": r.get("localizedDate") or "",
					"text": extract_review_text(r),
				}
			)

	all_reviews.sort(key=lambda x: x.get("created_at") or "", reverse=True)

	rated_values = [
		r["rating"] for r in all_reviews if isinstance(r.get("rating"), (int, float))
	]
	avg_rating = (
		round(sum(rated_values) / len(rated_values), 2) if rated_values else None
	)

	iso_dates = sorted(r["created_at"] for r in all_reviews if r.get("created_at"))
	date_range = {
		"earliest": iso_dates[0] if iso_dates else None,
		"latest": iso_dates[-1] if iso_dates else None,
	}

	rating_distribution = {
		str(star): rating_counts.get(star, 0) for star in range(5, 0, -1)
	}

	return {
		"host_id": str(host_id),
		"host_name": host_name or "Unknown",
		"is_superhost": is_superhost,
		"check_in": check_in,
		"check_out": check_out,
		"currency": currency,
		"listing_count": len(listings_out),
		"total_reviews_fetched": len(all_reviews),
		"total_reviews_expected": expected_total_reviews,
		"average_rating": avg_rating,
		"rating_distribution": rating_distribution,
		"date_range": date_range,
		"recurring_praise": _extract_themes(all_reviews, _PRAISE_THEMES),
		"recurring_issues": _extract_themes(all_reviews, _ISSUE_THEMES),
		"listings": listings_out,
		"reviews": all_reviews,
	}


def format_host_report(report, show_reviews=False, search_reviews=None):
	"""Format a consolidated host review report for terminal output."""
	lines = []
	host_label = report.get("host_name") or "Unknown"
	if report.get("is_superhost"):
		host_label += " (Superhost)"
	lines.append(f"\n# Host Review: {host_label} (ID: {report['host_id']})")

	avg_str = (
		f"★ {report['average_rating']}"
		if report.get("average_rating") is not None
		else "N/A"
	)
	fetched = report.get("total_reviews_fetched", 0)
	expected = report.get("total_reviews_expected", 0)
	count_note = (
		f"{fetched} reviews (matches listing sum {expected})"
		if fetched == expected
		else f"{fetched} fetched / {expected} expected across listings"
	)
	lines.append(
		f"Listings:    {report.get('listing_count', 0)} | Average Rating: {avg_str} | Total: {count_note}"
	)

	dr = report.get("date_range") or {}
	if dr.get("earliest") and dr.get("latest"):
		lines.append(f"Date Range:  {dr['earliest']} to {dr['latest']}")

	dist = report.get("rating_distribution") or {}
	total_rated = sum(dist.values())
	if total_rated:
		dist_parts = []
		for star in ("5", "4", "3", "2", "1"):
			cnt = dist.get(star, 0)
			if cnt:
				pct = round((cnt / total_rated) * 100, 1)
				dist_parts.append(f"{star}★: {cnt} ({pct}%)")
		lines.append(f"Ratings:     {' | '.join(dist_parts)}")

	restricted_listings = [
		item for item in report.get("listings", []) if item.get("visitor_restricted")
	]
	if restricted_listings:
		lines.append(
			f"Visitors:    [FLAG: Visitors Restricted on {len(restricted_listings)}/{report.get('listing_count', 0)} listings]"
		)

	lines.append("\n## Per-Listing Breakdown")
	for idx, item in enumerate(report.get("listings", []), 1):
		rating_str = (
			f"★{item['rating']}" if item.get("rating") is not None else "No rating"
		)
		cap_str = (
			f"{item['person_capacity']} guests"
			if item.get("person_capacity")
			else item.get("room_type", "")
		)
		flags_str = f" {' '.join(item['flags'])}" if item.get("flags") else ""
		lines.append(f"{idx}. {item['title']}{flags_str}")
		lines.append(f"   URL:     {item['url']}")
		price = item.get("price")
		if price:
			disc_part = (
				f", {price['discount_pct']}% discount"
				if price.get("discount_pct")
				else ""
			)
			price_str = f"{price['currency']} ${price['amount']:.2f} total (${price['nightly']:.2f}/nt{disc_part})"
		else:
			price_str = (
				f"Unavailable for {report['check_in']} -> {report['check_out']}"
				if report.get("check_in") and report.get("check_out")
				else "Price not queried"
			)
		lines.append(
			f"   Stats:   {rating_str} ({item['fetched_review_count']}/{item['expected_review_count']} reviews) | {cap_str} | {price_str}"
		)
		if item.get("visitor_restricted") and item.get("visitor_rule"):
			lines.append(f"   Rule:    {item['visitor_rule']}")

	praise = report.get("recurring_praise") or []
	issues = report.get("recurring_issues") or []
	if praise or issues:
		lines.append("\n## Recurring Themes")
		for p in praise:
			lines.append(f'+ {p["theme"]} ({p["count"]} mentions): "{p["sample"]}"')
		for iss in issues:
			lines.append(
				f'- {iss["theme"]} ({iss["count"]} mentions): "{iss["sample"]}"'
			)

	if show_reviews or search_reviews:
		all_revs = report.get("reviews") or []
		pattern = re.compile(search_reviews, re.IGNORECASE) if search_reviews else None
		filtered = [
			r for r in all_revs if not pattern or pattern.search(r.get("text") or "")
		]
		hdr = (
			f"\n## Reviews Matching '{search_reviews}' ({len(filtered)}/{len(all_revs)})"
			if search_reviews
			else f"\n## All Host Reviews ({len(filtered)})"
		)
		lines.append(hdr)
		for idx, rev in enumerate(filtered, 1):
			date_str = rev.get("created_at") or rev.get("localized_date") or ""
			meta = " | ".join(
				str(x)
				for x in [
					rev.get("listing_title"),
					rev.get("author"),
					date_str,
					f"★{rev['rating']}" if rev.get("rating") is not None else None,
				]
				if x
			)
			lines.append(f"{idx}. [{meta}] {rev.get('text', '')}")

	return "\n".join(lines)
