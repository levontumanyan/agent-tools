#!/usr/bin/env python3
"""Check Airbnb listings' house rules for visitor policies.

Fetches listing details via the CLI's authenticated fetcher (force refresh)
and reports whether visitors are allowed, restricted, or banned.

Usage:
	uv run python scripts/check_visitors.py --ids 1105958712020626112,1452874078261275321
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fetcher import get_listing_details  # noqa: E402


def summarize(listing_id: str, currency: str = "CAD") -> dict:
	details = get_listing_details(listing_id, currency=currency, force_refresh=True)
	if not details:
		return {"id": listing_id, "status": "FETCH_FAILED"}

	hr = details.get("house_rules") or {}
	aditional = (hr.get("aditional") or "").strip()
	rules = []
	for group in hr.get("general") or []:
		for value in group.get("values") or []:
			rules.append(value.get("title", ""))

	extra_text = " ".join(
		section.get("body", "")
		for section in details.get("sections", [])
		if isinstance(section, dict)
	)
	description = details.get("description") or ""
	sub_description = ""
	sub = details.get("sub_description")
	if isinstance(sub, dict):
		sub_description = sub.get("text") or sub.get("title") or ""
	elif isinstance(sub, str):
		sub_description = sub
	blob = " ".join(
		[
			aditional,
			" ".join(rules),
			description,
			sub_description,
			extra_text,
		]
	)
	blob_l = blob.lower()

	if re.search(
		r"visitors? (are )?not (allowed|permitted)|visitantes? n(ã|a)o (s(ã|a)o )?(permitid|autorizad)|n(ã|a)o (é|e) permitid[oa]s? visitantes",
		blob_l,
	):
		verdict = "NO_VISITORS"
	elif re.search(r"visitor", blob_l):
		verdict = "VISITOR_RULE_PRESENT"
	else:
		verdict = "NO_EXPLICIT_RULE"

	return {
		"id": listing_id,
		"status": "OK",
		"verdict": verdict,
		"rules": rules,
		"aditional": aditional[:500],
		"context": (re.search(r"[^\n]{0,110}visitor[^\n]{0,160}", blob_l) or [None])[0],
	}


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Check Airbnb house rules for visitor policies"
	)
	parser.add_argument("--ids", required=True, help="Comma-separated listing IDs")
	parser.add_argument(
		"--currency", default="CAD", help="Currency for pricing context (default CAD)"
	)
	args = parser.parse_args()

	for listing_id in [i.strip() for i in args.ids.split(",") if i.strip()]:
		result = summarize(listing_id, args.currency)
		print(f"===== {listing_id} =====")
		print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
	main()
