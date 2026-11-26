from models import FlightItinerary, FlightLeg
from scorer import FlightScorer


def sample_benchmarks():
	return {
		"metrics": {
			"price_efficiency": {
				"weight": 0.50,
				"function": "price_to_market_min",
			},
			"duration_efficiency": {
				"weight": 0.50,
				"function": "duration_to_min",
			},
		},
		"penalties": [
			{
				"name": "Tight Layover (<75m)",
				"condition": {
					"field": "min_layover_minutes",
					"operator": "<",
					"value": 75,
					"require_stops": True,
				},
				"multiplier": 0.6,
			},
			{
				"name": "Overnight Layover",
				"condition": {
					"field": "has_overnight_layover",
					"operator": "==",
					"value": True,
				},
				"multiplier": 0.5,
			},
		],
		"hard_filters": {
			"max_stops": 1,
			"max_price": 1000,
			"min_layover_minutes": 45,
		},
	}


def test_scorer_direct_flight_perfect_score():
	benchmarks = sample_benchmarks()
	leg = FlightLeg(
		origin_code="YUL",
		origin_name="Montreal",
		destination_code="CDG",
		destination_name="Paris",
		departure_time="2026-10-20 19:30",
		arrival_time="2026-10-21 08:00",
		duration_minutes=390,
		airline="Air Canada",
	)
	itin = FlightItinerary(
		id="direct_itin",
		provider="fast-flights",
		airlines=["Air Canada"],
		origin="YUL",
		destination="CDG",
		departure_time="2026-10-20 19:30",
		arrival_time="2026-10-21 08:00",
		total_duration_minutes=390,
		stops=0,
		price=500.0,
		currency="CAD",
		legs=[leg],
	)

	scorer = FlightScorer(benchmarks, min_market_price=500.0, min_market_duration=390)
	scored = scorer.score(itin)

	assert scored.passed
	assert scored.base_score == 100.0
	assert scored.final_score == 100.0
	assert len(scored.applied_penalties) == 0


def test_scorer_penalty_stacking():
	benchmarks = sample_benchmarks()
	leg1 = FlightLeg(
		origin_code="YUL",
		origin_name="Montreal",
		destination_code="LHR",
		destination_name="London",
		departure_time="2026-10-20 10:00",
		arrival_time="2026-10-20 21:00",
		duration_minutes=420,
		layover_minutes_to_next=60,  # Tight layover (<75m)
	)
	leg2 = FlightLeg(
		origin_code="LHR",
		origin_name="London",
		destination_code="CDG",
		destination_name="Paris",
		departure_time="2026-10-20 22:00",
		arrival_time="2026-10-20 23:15",
		duration_minutes=75,
	)
	itin = FlightItinerary(
		id="tight_layover_itin",
		provider="fast-flights",
		airlines=["British Airways"],
		origin="YUL",
		destination="CDG",
		departure_time="2026-10-20 10:00",
		arrival_time="2026-10-20 23:15",
		total_duration_minutes=555,
		stops=1,
		price=500.0,
		currency="CAD",
		legs=[leg1, leg2],
	)

	scorer = FlightScorer(benchmarks, min_market_price=500.0, min_market_duration=390)
	scored = scorer.score(itin)

	assert scored.passed
	# Tight layover applies 0.6 multiplier
	assert any("Tight Layover" in p for p in scored.applied_penalties)
	assert scored.final_score < scored.base_score
	assert round(scored.final_score, 1) == round(scored.base_score * 0.6, 1)


def test_scorer_hard_filter_failure():
	benchmarks = sample_benchmarks()
	itin = FlightItinerary(
		id="too_expensive",
		provider="fast-flights",
		airlines=["Air France"],
		origin="YUL",
		destination="CDG",
		departure_time="2026-10-20 19:30",
		arrival_time="2026-10-21 08:00",
		total_duration_minutes=390,
		stops=0,
		price=1500.0,  # Exceeds max_price 1000
		currency="CAD",
		legs=[],
	)

	scorer = FlightScorer(benchmarks, min_market_price=500.0, min_market_duration=390)
	scored = scorer.score(itin)

	assert not scored.passed
	assert scored.final_score == 0.0
	assert any("max price" in f for f in scored.failed_hard_filters)
