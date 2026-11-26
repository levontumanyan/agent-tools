from models import FlightItinerary, FlightLeg, FlightSearchQuery


def test_flight_leg_creation():
	leg = FlightLeg(
		origin_code="YUL",
		origin_name="Montreal-Trudeau",
		destination_code="CDG",
		destination_name="Paris Charles de Gaulle",
		departure_time="2026-10-20 20:00",
		arrival_time="2026-10-21 08:30",
		duration_minutes=450,
		airline="Air France",
		aircraft="Boeing 777",
	)
	assert leg.origin_code == "YUL"
	assert leg.duration_minutes == 450
	assert leg.layover_minutes_to_next is None


def test_flight_itinerary_properties():
	leg1 = FlightLeg(
		origin_code="YUL",
		origin_name="Montreal",
		destination_code="LHR",
		destination_name="Heathrow",
		departure_time="2026-10-20 18:00",
		arrival_time="2026-10-21 06:00",
		duration_minutes=420,
		airline="British Airways",
		layover_minutes_to_next=90,
	)
	leg2 = FlightLeg(
		origin_code="LHR",
		origin_name="Heathrow",
		destination_code="CDG",
		destination_name="Charles de Gaulle",
		departure_time="2026-10-21 07:30",
		arrival_time="2026-10-21 09:45",
		duration_minutes=75,
		airline="British Airways",
		layover_minutes_to_next=None,
	)
	itin = FlightItinerary(
		id="test_id_123",
		provider="fast-flights",
		airlines=["British Airways"],
		origin="YUL",
		destination="CDG",
		departure_time="2026-10-20 18:00",
		arrival_time="2026-10-21 09:45",
		total_duration_minutes=585,
		stops=1,
		price=850.0,
		currency="CAD",
		legs=[leg1, leg2],
	)

	assert itin.layovers == [90]
	assert itin.max_layover_minutes == 90
	assert itin.min_layover_minutes == 90
	assert not itin.has_overnight_layover


def test_flight_itinerary_overnight_layover():
	leg1 = FlightLeg(
		origin_code="JFK",
		origin_name="JFK",
		destination_code="LAS",
		destination_name="Las Vegas",
		departure_time="2026-10-20 19:00",
		arrival_time="2026-10-20 22:00",
		duration_minutes=360,
		layover_minutes_to_next=500,  # 8+ hours
	)
	leg2 = FlightLeg(
		origin_code="LAS",
		origin_name="Las Vegas",
		destination_code="LAX",
		destination_name="Los Angeles",
		departure_time="2026-10-21 06:20",
		arrival_time="2026-10-21 07:30",
		duration_minutes=70,
	)
	itin = FlightItinerary(
		id="test_overnight",
		provider="fast-flights",
		airlines=["American"],
		origin="JFK",
		destination="LAX",
		departure_time="2026-10-20 19:00",
		arrival_time="2026-10-21 07:30",
		total_duration_minutes=930,
		stops=1,
		price=250.0,
		currency="USD",
		legs=[leg1, leg2],
	)
	assert itin.has_overnight_layover


def test_search_query_cache_key():
	q1 = FlightSearchQuery(
		origin="YUL",
		destination="CDG",
		date="2026-10-20",
		currency="CAD",
		seat="economy",
	)
	assert q1.cache_key == "FAST-FLIGHTS_YUL_CDG_2026-10-20_ECONOMY_CAD"

	q2 = FlightSearchQuery(
		origin="YUL",
		destination="CDG",
		date="2026-10-20",
		return_date="2026-10-30",
		currency="CAD",
		seat="business",
	)
	assert q2.cache_key == "FAST-FLIGHTS_YUL_CDG_2026-10-20_2026-10-30_BUSINESS_CAD"
