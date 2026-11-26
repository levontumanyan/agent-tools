import json
from unittest.mock import MagicMock, patch

from models import FlightSearchQuery
from providers.fast_flights_provider import FastFlightsProvider


def test_fast_flights_provider_parsing():
	provider = FastFlightsProvider()
	assert provider.name == "fast-flights"

	query = FlightSearchQuery(
		origin="YUL",
		destination="CDG",
		date="2026-11-10",
		currency="CAD",
	)

	# Sample html containing script.ds:1 with flight payload
	leg_item = [
		None,
		None,
		None,
		"YUL",
		"Montreal-Trudeau",
		"CDG",
		"CDG",
		None,
		[20, 0],
		None,
		[8, 30],
		450,
		None,
		None,
		None,
		None,
		None,
		"Airbus A350-900",
		None,
		None,
		[2026, 11, 10],
		[2026, 11, 11],
	]
	flight_data = ["AF", ["Air France"], [leg_item]]
	price_data = [[None, 620.0]]
	itinerary_item = [flight_data, price_data]

	mock_json = json.dumps([None, None, [], [[itinerary_item]]])
	mock_html = f'<html><body><script class="ds:1">/* ... */ data:{mock_json}, sideChannel: {{}}</script></body></html>'

	with patch(
		"providers.fast_flights_provider.fetch_flights_html", return_value=mock_html
	):
		with patch("providers.fast_flights_provider.create_query") as mock_cq:
			mock_q_obj = MagicMock()
			mock_q_obj.url.return_value = "https://google.com/travel/flights/..."
			mock_cq.return_value = mock_q_obj

			results = provider.search(query)

	assert len(results) == 1
	it = results[0]
	assert it.origin == "YUL"
	assert it.destination == "CDG"
	assert it.price == 620.0
	assert it.airlines == ["Air France"]
	assert it.stops == 0
	assert len(it.legs) == 1
	assert it.legs[0].aircraft == "Airbus A350-900"
