import logging
from datetime import datetime
from typing import Any

from models import FlightItinerary, ScoredFlight

logger = logging.getLogger("flights")


class FlightScorer:
	"""Scores flight itineraries based on hard filters, weighted metrics, and penalty multipliers."""

	def __init__(
		self,
		benchmarks: dict[str, Any],
		min_market_price: float = 0.0,
		min_market_duration: int = 0,
		hard_filter_overrides: dict[str, Any] | None = None,
	):
		self.benchmarks = benchmarks
		self.metrics = benchmarks.get("metrics", {})
		self.penalties = benchmarks.get("penalties", [])
		self.hard_filters = benchmarks.get("hard_filters", {}).copy()

		if hard_filter_overrides:
			for k, v in hard_filter_overrides.items():
				if v is not None:
					self.hard_filters[k] = v

		self.min_market_price = min_market_price
		self.min_market_duration = min_market_duration

	def score(self, itinerary: FlightItinerary) -> ScoredFlight:
		# 1. Hard filters check
		failed_filters = self._check_hard_filters(itinerary)
		if failed_filters:
			return ScoredFlight(
				itinerary=itinerary,
				base_score=0.0,
				final_score=0.0,
				metric_scores={},
				applied_penalties=[f"FAILED: {f}" for f in failed_filters],
				failed_hard_filters=failed_filters,
			)

		# 2. Weighted base score
		base_score = 0.0
		metric_scores: dict[str, float] = {}

		for name, config in self.metrics.items():
			func_name = config.get("function")
			weight = config.get("weight", 0.0)
			params = config.get("params", {})

			score = self._compute_metric(func_name, itinerary, params)
			metric_scores[name] = round(score, 2)
			base_score += score * weight

		# 3. Stackable penalties
		final_score = base_score
		applied_penalties: list[str] = []

		for penalty in self.penalties:
			cond = penalty.get("condition", {})
			multiplier = penalty.get("multiplier", 1.0)
			name = penalty.get("name", "Unknown Penalty")

			if self._matches_condition(cond, itinerary):
				final_score *= multiplier
				applied_penalties.append(f"{name} ({multiplier}x)")

		return ScoredFlight(
			itinerary=itinerary,
			base_score=round(base_score, 2),
			final_score=round(final_score, 2),
			metric_scores=metric_scores,
			applied_penalties=applied_penalties,
			failed_hard_filters=[],
		)

	def _check_hard_filters(self, it: FlightItinerary) -> list[str]:
		failed = []
		max_stops = self.hard_filters.get("max_stops")
		if max_stops is not None and it.stops > max_stops:
			failed.append(f"Exceeds max stops ({it.stops} > {max_stops})")

		max_price = self.hard_filters.get("max_price")
		if max_price is not None and it.price > max_price:
			failed.append(f"Exceeds max price ({it.price} > {max_price})")

		max_duration = self.hard_filters.get("max_duration_minutes")
		if max_duration is not None and it.total_duration_minutes > max_duration:
			failed.append(
				f"Exceeds max duration ({it.total_duration_minutes}m > {max_duration}m)"
			)

		min_layover = self.hard_filters.get("min_layover_minutes")
		if min_layover is not None and it.stops > 0:
			if it.min_layover_minutes < min_layover:
				failed.append(
					f"Layover too short ({it.min_layover_minutes}m < {min_layover}m)"
				)

		return failed

	def _compute_metric(
		self, func_name: str, it: FlightItinerary, params: dict[str, Any]
	) -> float:
		if func_name == "price_to_market_min":
			if it.price <= 0 or self.min_market_price <= 0:
				return 50.0
			return min(100.0, (self.min_market_price / it.price) * 100.0)

		if func_name in ("duration_efficiency", "duration_to_min"):
			if it.total_duration_minutes <= 0 or self.min_market_duration <= 0:
				return 50.0
			return min(
				100.0,
				(self.min_market_duration / it.total_duration_minutes) * 100.0,
			)

		if func_name == "time_of_day_score":
			try:
				dt = datetime.strptime(it.departure_time, "%Y-%m-%d %H:%M")
				hour = dt.hour
			except (ValueError, TypeError):
				hour = 12

			prime_start = params.get("prime_start_hour", 8)
			prime_end = params.get("prime_end_hour", 19)
			acc_start = params.get("acceptable_start_hour", 6)
			acc_end = params.get("acceptable_end_hour", 22)

			if prime_start <= hour <= prime_end:
				return 100.0
			if acc_start <= hour <= acc_end:
				return 75.0
			return 40.0

		if func_name == "airline_tier":
			preferred = params.get("preferred_airlines", [])
			budget = params.get("budget_airlines", [])

			primary_airline = it.airlines[0] if it.airlines else ""
			for p in preferred:
				if p.lower() in primary_airline.lower():
					return 100.0
			for b in budget:
				if b.lower() in primary_airline.lower():
					return 50.0
			return 80.0

		return 50.0

	def _matches_condition(self, cond: dict[str, Any], it: FlightItinerary) -> bool:
		field = cond.get("field")
		op = cond.get("operator")
		val = cond.get("value")
		require_stops = cond.get("require_stops", False)

		if require_stops and it.stops == 0:
			return False

		actual_val = getattr(it, field, None)
		if actual_val is None:
			return False

		if op == "<":
			return bool(actual_val < val)
		if op == "<=":
			return bool(actual_val <= val)
		if op == ">":
			return bool(actual_val > val)
		if op == ">=":
			return bool(actual_val >= val)
		if op == "==":
			return bool(actual_val == val)
		if op == "!=":
			return bool(actual_val != val)

		return False
