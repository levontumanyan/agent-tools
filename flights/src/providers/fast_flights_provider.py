import json
import logging
from datetime import datetime
from typing import Any

from fast_flights import FlightQuery, create_query
from fast_flights.fetcher import fetch_flights_html
from selectolax.lexbor import LexborHTMLParser

from models import FlightItinerary, FlightLeg, FlightSearchQuery
from providers.base import BaseFlightProvider

logger = logging.getLogger("flights")


class FastFlightsProvider(BaseFlightProvider):
	"""Google Flights provider powered by fast-flights reverse-engineered client."""

	@property
	def name(self) -> str:
		return "fast-flights"

	def search(self, query: FlightSearchQuery) -> list[FlightItinerary]:
		logger.info(
			f"[{self.name}] Searching flights {query.origin} -> {query.destination} on {query.date} ({query.seat}, {query.currency})..."
		)

		flight_queries = [
			FlightQuery(
				date=query.date,
				from_airport=query.origin,
				to_airport=query.destination,
				max_stops=query.max_stops,
			)
		]

		if query.trip_type == "round-trip" and query.return_date:
			flight_queries.append(
				FlightQuery(
					date=query.return_date,
					from_airport=query.destination,
					to_airport=query.origin,
					max_stops=query.max_stops,
				)
			)

		seat_mapping = {
			"economy": "economy",
			"premium-economy": "premium-economy",
			"business": "business",
			"first": "first",
		}
		seat_val = seat_mapping.get(query.seat.lower(), "economy")
		trip_val = "round-trip" if query.trip_type == "round-trip" else "one-way"

		try:
			q = create_query(
				flights=flight_queries,
				seat=seat_val,  # type: ignore[arg-type]
				trip=trip_val,  # type: ignore[arg-type]
				currency=query.currency,  # type: ignore[arg-type]
				max_stops=query.max_stops,
				max_price=query.max_price,
			)
			html = fetch_flights_html(q)
		except Exception as e:
			logger.error(f"[{self.name}] Failed to fetch flight HTML: {e}")
			return []

		search_url = q.url() if hasattr(q, "url") else ""
		itineraries = self._parse_html(html, query, search_url)

		logger.info(f"[{self.name}] Found {len(itineraries)} valid itineraries.")
		return itineraries

	def _parse_html(
		self, html: str, query: FlightSearchQuery, search_url: str
	) -> list[FlightItinerary]:
		parser = LexborHTMLParser(html)
		script = parser.css_first(r"script.ds\:1")
		if not script:
			return []

		try:
			data = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
			payload = json.loads(data)
		except Exception as e:
			logger.error(f"[{self.name}] Failed to parse JSON script data: {e}")
			return []

		# Aggregate both "Top flights" (payload[3][0]) and "Other flights" (payload[2][0])
		raw_items: list[Any] = []
		if len(payload) > 3 and payload[3] and payload[3][0]:
			raw_items.extend(payload[3][0])
		if len(payload) > 2 and payload[2] and payload[2][0]:
			raw_items.extend(payload[2][0])

		itineraries: list[FlightItinerary] = []
		for item in raw_items:
			itin = self._parse_raw_item(item, query, search_url)
			if itin:
				itineraries.append(itin)

		return itineraries

	def _parse_raw_item(
		self, item: Any, query: FlightSearchQuery, search_url: str
	) -> FlightItinerary | None:
		try:
			flight_data = (
				item[0]
				if (
					isinstance(item, list)
					and len(item) > 0
					and isinstance(item[0], list)
				)
				else []
			)
			if not flight_data:
				return None

			airlines = (
				flight_data[1]
				if len(flight_data) > 1 and flight_data[1]
				else ["Unknown Airline"]
			)

			# Price extraction safely handling empty or nested lists
			price = 0.0
			if len(item) > 1 and item[1] and len(item[1]) > 0:
				p_elem = item[1][0]
				if (
					isinstance(p_elem, list)
					and len(p_elem) > 1
					and p_elem[1] is not None
				):
					try:
						price = float(p_elem[1])
					except (ValueError, TypeError):
						price = 0.0

			raw_legs = flight_data[2] if len(flight_data) > 2 else []
			if not raw_legs:
				return None

			parsed_legs: list[FlightLeg] = []
			for leg in raw_legs:
				from_code = leg[3] or ""
				from_name = leg[4] or ""
				to_code = leg[6] or ""
				to_name = leg[5] or ""

				dep_time_tuple = leg[8] if len(leg) > 8 else None
				dep_h = (
					dep_time_tuple[0]
					if (dep_time_tuple and len(dep_time_tuple) > 0)
					else 0
				)
				dep_m = (
					dep_time_tuple[1]
					if (dep_time_tuple and len(dep_time_tuple) > 1)
					else 0
				)

				arr_time_tuple = leg[10] if len(leg) > 10 else None
				arr_h = (
					arr_time_tuple[0]
					if (arr_time_tuple and len(arr_time_tuple) > 0)
					else 0
				)
				arr_m = (
					arr_time_tuple[1]
					if (arr_time_tuple and len(arr_time_tuple) > 1)
					else 0
				)

				dep_d_tuple = leg[20] if len(leg) > 20 else None
				arr_d_tuple = leg[21] if len(leg) > 21 else None

				if not dep_d_tuple or not arr_d_tuple:
					return None

				dep_dt = datetime(
					dep_d_tuple[0], dep_d_tuple[1], dep_d_tuple[2], dep_h, dep_m
				)
				arr_dt = datetime(
					arr_d_tuple[0], arr_d_tuple[1], arr_d_tuple[2], arr_h, arr_m
				)

				dur = int(leg[11]) if len(leg) > 11 and leg[11] else 0
				plane = leg[17] if len(leg) > 17 and leg[17] else ""
				leg_airline = airlines[0] if airlines else ""

				parsed_legs.append(
					FlightLeg(
						origin_code=from_code,
						origin_name=from_name,
						destination_code=to_code,
						destination_name=to_name,
						departure_time=dep_dt.strftime("%Y-%m-%d %H:%M"),
						arrival_time=arr_dt.strftime("%Y-%m-%d %H:%M"),
						duration_minutes=dur,
						airline=leg_airline,
						aircraft=plane,
					)
				)

			# Calculate layovers
			for i in range(len(parsed_legs) - 1):
				t_arr = datetime.strptime(parsed_legs[i].arrival_time, "%Y-%m-%d %H:%M")
				t_next = datetime.strptime(
					parsed_legs[i + 1].departure_time, "%Y-%m-%d %H:%M"
				)
				diff_m = int((t_next - t_arr).total_seconds() / 60)
				parsed_legs[i].layover_minutes_to_next = max(0, diff_m)

			total_duration = sum(lg.duration_minutes for lg in parsed_legs) + sum(
				lg.layover_minutes_to_next or 0 for lg in parsed_legs
			)
			stops = max(0, len(parsed_legs) - 1)

			itin_id = FlightItinerary.compute_id(parsed_legs, price, query.currency)

			return FlightItinerary(
				id=itin_id,
				provider=self.name,
				airlines=airlines,
				origin=parsed_legs[0].origin_code,
				destination=parsed_legs[-1].destination_code,
				departure_time=parsed_legs[0].departure_time,
				arrival_time=parsed_legs[-1].arrival_time,
				total_duration_minutes=total_duration,
				stops=stops,
				price=price,
				currency=query.currency,
				legs=parsed_legs,
				url=search_url,
			)
		except Exception as e:
			logger.warning(f"[{self.name}] Error parsing itinerary item: {e}")
			return None
