import argparse
import sys
from datetime import datetime, timedelta

from config import DEFAULT_CURRENCY, DEFAULT_PROVIDER, DEFAULT_SEAT_CLASS
from fetcher import fetch_flights
from models import FlightSearchQuery
from reporter import generate_csv_report, generate_json_report, print_cli_table
from scorer import FlightScorer
from utils import load_benchmarks, setup_logging


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Search, score, and rank flight options based on custom utility benchmarks."
	)
	parser.add_argument(
		"--origin",
		"-o",
		required=True,
		help="Origin airport IATA code (e.g. YUL, JFK, LHR)",
	)
	parser.add_argument(
		"--destination",
		"-d",
		required=True,
		help="Destination airport IATA code (e.g. LAX, CDG, NRT)",
	)
	parser.add_argument(
		"--date",
		help="Departure date (YYYY-MM-DD). Defaults to 30 days from today.",
	)
	parser.add_argument(
		"--return_date",
		"-r",
		help="Optional return date for round trips (YYYY-MM-DD).",
	)
	parser.add_argument(
		"--trip_type",
		choices=["one-way", "round-trip"],
		help="Trip type. Inferred as round-trip if --return_date is specified.",
	)
	parser.add_argument(
		"--seat",
		default=DEFAULT_SEAT_CLASS,
		choices=["economy", "premium-economy", "business", "first"],
		help=f"Cabin class (default: {DEFAULT_SEAT_CLASS})",
	)
	parser.add_argument(
		"--currency",
		default=DEFAULT_CURRENCY,
		help=f"Currency for pricing (default: {DEFAULT_CURRENCY})",
	)
	parser.add_argument(
		"--provider",
		default=DEFAULT_PROVIDER,
		help=f"Data provider to use (default: {DEFAULT_PROVIDER})",
	)
	parser.add_argument(
		"--max_stops",
		type=int,
		help="Filter by maximum number of stops allowed",
	)
	parser.add_argument(
		"--max_price",
		type=float,
		help="Filter by maximum price threshold",
	)
	parser.add_argument(
		"--limit",
		type=int,
		default=15,
		help="Number of results to display in terminal table (default: 15)",
	)
	parser.add_argument(
		"--csv",
		action="store_true",
		help="Generate a timestamped CSV report in reports/",
	)
	parser.add_argument(
		"--json",
		action="store_true",
		help="Generate a timestamped JSON report in reports/",
	)
	parser.add_argument(
		"--force_refresh",
		action="store_true",
		help="Bypass local cache and query live provider",
	)
	parser.add_argument(
		"--verbose",
		"-v",
		action="store_true",
		help="Enable debug logging",
	)
	return parser.parse_args()


def main():
	args = parse_args()
	setup_logging(verbose=args.verbose)

	dep_date = args.date
	if not dep_date:
		dep_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

	trip_type = args.trip_type
	if not trip_type:
		trip_type = "round-trip" if args.return_date else "one-way"

	origin = args.origin.upper().strip()
	destination = args.destination.upper().strip()

	print(f"\n🔍 Searching flights: {origin} -> {destination} on {dep_date}")
	if args.return_date:
		print(f"🔄 Return date: {args.return_date}")
	print(f"💰 Currency: {args.currency} | Provider: {args.provider}\n")

	query = FlightSearchQuery(
		origin=origin,
		destination=destination,
		date=dep_date,
		return_date=args.return_date,
		trip_type=trip_type,
		seat=args.seat,
		currency=args.currency,
		max_stops=args.max_stops,
		max_price=int(args.max_price) if args.max_price else None,
		provider=args.provider,
	)

	itineraries = fetch_flights(query, force_refresh=args.force_refresh)

	if not itineraries:
		print("❌ No flight itineraries found.")
		sys.exit(0)

	# Calculate market baselines (min price, min duration) among available flights
	valid_prices = [it.price for it in itineraries if it.price > 0]
	min_market_price = min(valid_prices) if valid_prices else 0.0

	valid_durations = [
		it.total_duration_minutes for it in itineraries if it.total_duration_minutes > 0
	]
	min_market_duration = min(valid_durations) if valid_durations else 0

	benchmarks = load_benchmarks()
	overrides = {
		"max_stops": args.max_stops,
		"max_price": args.max_price,
	}

	scorer = FlightScorer(
		benchmarks=benchmarks,
		min_market_price=min_market_price,
		min_market_duration=min_market_duration,
		hard_filter_overrides=overrides,
	)

	scored_flights = [scorer.score(it) for it in itineraries]

	# Sort by final score descending, then by price ascending
	scored_flights.sort(key=lambda s: (-s.final_score, s.itinerary.price))

	# Filter out failed hard filters for the top display, but preserve if all failed
	passed_flights = [sf for sf in scored_flights if sf.passed]
	display_flights = passed_flights if passed_flights else scored_flights

	print_cli_table(display_flights, limit=args.limit)

	if args.csv:
		csv_path = generate_csv_report(scored_flights, origin, destination, dep_date)
		print(f"📄 CSV report saved: {csv_path}")

	if args.json:
		json_path = generate_json_report(scored_flights, origin, destination, dep_date)
		print(f"📊 JSON report saved: {json_path}")


if __name__ == "__main__":
	main()
