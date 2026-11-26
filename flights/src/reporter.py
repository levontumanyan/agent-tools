import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from config import REPORTS_DIR
from models import ScoredFlight

logger = logging.getLogger("flights")


def format_duration(minutes: int) -> str:
	h = minutes // 60
	m = minutes % 60
	return f"{h}h {m:02d}m"


def print_cli_table(scored_flights: list[ScoredFlight], limit: int = 15):
	"""Prints a clean ASCII table of ranked flights to stdout."""
	if not scored_flights:
		print("\nNo flights found matching your criteria.\n")
		return

	rows = []
	for rank, sf in enumerate(scored_flights[:limit], start=1):
		it = sf.itinerary
		airlines_str = ", ".join(it.airlines[:2])
		route_str = f"{it.origin} -> {it.destination}"
		dep_time = (
			it.departure_time.split(" ")[1]
			if " " in it.departure_time
			else it.departure_time
		)
		arr_time = (
			it.arrival_time.split(" ")[1] if " " in it.arrival_time else it.arrival_time
		)
		time_str = f"{dep_time} - {arr_time}"
		stops_str = "Direct" if it.stops == 0 else f"{it.stops} stop"
		if it.stops > 0 and it.layovers:
			stops_str += f" ({format_duration(it.layovers[0])})"
		dur_str = format_duration(it.total_duration_minutes)
		if it.price > 0:
			if it.currency.upper() == "CAD":
				price_str = f"CA${it.price:,.0f}"
			elif it.currency.upper() == "USD":
				price_str = f"${it.price:,.0f} USD"
			else:
				price_str = f"{it.price:,.0f} {it.currency}"
		else:
			price_str = "Check site"
		penalties_str = (
			", ".join(sf.applied_penalties[:2]) if sf.applied_penalties else "None"
		)

		rows.append(
			(
				f"#{rank}",
				f"{sf.final_score:.1f}",
				airlines_str[:16],
				route_str,
				time_str,
				stops_str[:18],
				dur_str,
				price_str,
				penalties_str[:28],
			)
		)

	headers = (
		"Rank",
		"Score",
		"Airline",
		"Route",
		"Time",
		"Stops/Layover",
		"Duration",
		"Price",
		"Penalties",
	)
	widths = [len(h) for h in headers]
	for row in rows:
		for i, col in enumerate(row):
			widths[i] = max(widths[i], len(col))

	sep_border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
	header_row = (
		"| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
	)

	print("\n" + sep_border)
	print(header_row)
	print(sep_border)
	for row in rows:
		data_row = (
			"| " + " | ".join(val.ljust(widths[i]) for i, val in enumerate(row)) + " |"
		)
		print(data_row)
	print(sep_border + "\n")


def generate_csv_report(
	scored_flights: list[ScoredFlight],
	origin: str,
	destination: str,
	date: str,
	output_path: Path | None = None,
) -> Path:
	"""Exports scored flight results to a CSV report."""
	if output_path is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		output_path = (
			REPORTS_DIR / f"flights_{origin}_{destination}_{date}_{timestamp}.csv"
		)

	headers = [
		"Rank",
		"Score",
		"Base Score",
		"Flight ID",
		"Airlines",
		"Origin",
		"Destination",
		"Departure",
		"Arrival",
		"Total Duration (min)",
		"Stops",
		"Price",
		"Currency",
		"Max Layover (min)",
		"Penalties Applied",
		"Failed Hard Filters",
		"Booking URL",
	]

	with open(output_path, "w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(headers)

		for rank, sf in enumerate(scored_flights, start=1):
			it = sf.itinerary
			writer.writerow(
				[
					rank,
					sf.final_score,
					sf.base_score,
					it.id,
					"; ".join(it.airlines),
					it.origin,
					it.destination,
					it.departure_time,
					it.arrival_time,
					it.total_duration_minutes,
					it.stops,
					it.price,
					it.currency,
					it.max_layover_minutes,
					"; ".join(sf.applied_penalties),
					"; ".join(sf.failed_hard_filters),
					it.url,
				]
			)

	logger.info(f"Saved CSV report to {output_path}")
	return output_path


def generate_json_report(
	scored_flights: list[ScoredFlight],
	origin: str,
	destination: str,
	date: str,
	output_path: Path | None = None,
) -> Path:
	"""Exports scored flight results to a JSON report."""
	if output_path is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		output_path = (
			REPORTS_DIR / f"flights_{origin}_{destination}_{date}_{timestamp}.json"
		)

	report_data = {
		"search": {
			"origin": origin,
			"destination": destination,
			"date": date,
			"total_results": len(scored_flights),
			"generated_at": datetime.now().isoformat(),
		},
		"results": [
			{
				"rank": idx,
				"score": sf.final_score,
				"base_score": sf.base_score,
				"metric_scores": sf.metric_scores,
				"applied_penalties": sf.applied_penalties,
				"failed_hard_filters": sf.failed_hard_filters,
				"itinerary": sf.itinerary.to_dict(),
			}
			for idx, sf in enumerate(scored_flights, start=1)
		],
	}

	with open(output_path, "w", encoding="utf-8") as f:
		json.dump(report_data, f, indent="\t")

	logger.info(f"Saved JSON report to {output_path}")
	return output_path
