import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FlightLeg:
	origin_code: str
	origin_name: str
	destination_code: str
	destination_name: str
	departure_time: str
	arrival_time: str
	duration_minutes: int
	airline: str = ""
	flight_number: str = ""
	aircraft: str = ""
	layover_minutes_to_next: int | None = None

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "FlightLeg":
		return cls(**data)


@dataclass
class FlightItinerary:
	id: str
	provider: str
	airlines: list[str]
	origin: str
	destination: str
	departure_time: str
	arrival_time: str
	total_duration_minutes: int
	stops: int
	price: float
	currency: str
	legs: list[FlightLeg] = field(default_factory=list)
	carbon_emissions: int | None = None
	typical_carbon_emissions: int | None = None
	url: str = ""

	@property
	def layovers(self) -> list[int]:
		return [
			leg.layover_minutes_to_next
			for leg in self.legs
			if leg.layover_minutes_to_next is not None
		]

	@property
	def max_layover_minutes(self) -> int:
		lays = self.layovers
		return max(lays) if lays else 0

	@property
	def min_layover_minutes(self) -> int:
		lays = self.layovers
		return min(lays) if lays else 0

	@property
	def has_overnight_layover(self) -> bool:
		# Layovers longer than 6 hours (360 mins) or crossing past midnight
		return self.max_layover_minutes >= 360

	def to_dict(self) -> dict[str, Any]:
		data = asdict(self)
		return data

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "FlightItinerary":
		legs_data = data.pop("legs", [])
		legs = [FlightLeg.from_dict(lg) for lg in legs_data]
		return cls(legs=legs, **data)

	@staticmethod
	def compute_id(legs: list[FlightLeg], price: float, currency: str) -> str:
		key_str = f"{price}:{currency}:" + ";".join(
			f"{leg.origin_code}-{leg.destination_code}-{leg.departure_time}-{leg.airline}"
			for leg in legs
		)
		return hashlib.md5(key_str.encode("utf-8")).hexdigest()[:12]


@dataclass
class FlightSearchQuery:
	origin: str
	destination: str
	date: str
	return_date: str | None = None
	trip_type: str = "one-way"
	seat: str = "economy"
	currency: str = "CAD"
	passengers: int = 1
	max_stops: int | None = None
	max_price: int | None = None
	provider: str = "fast-flights"

	@property
	def cache_key(self) -> str:
		ret = f"_{self.return_date}" if self.return_date else ""
		return f"{self.provider}_{self.origin}_{self.destination}_{self.date}{ret}_{self.seat}_{self.currency}".upper()


@dataclass
class ScoredFlight:
	itinerary: FlightItinerary
	base_score: float
	final_score: float
	metric_scores: dict[str, float] = field(default_factory=dict)
	applied_penalties: list[str] = field(default_factory=list)
	failed_hard_filters: list[str] = field(default_factory=list)

	@property
	def passed(self) -> bool:
		return len(self.failed_hard_filters) == 0
