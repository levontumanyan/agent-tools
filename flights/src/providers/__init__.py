from providers.base import BaseFlightProvider
from providers.fast_flights_provider import FastFlightsProvider

PROVIDERS: dict[str, type[BaseFlightProvider]] = {
	"fast-flights": FastFlightsProvider,
}


def get_provider(name: str = "fast-flights") -> BaseFlightProvider:
	provider_cls = PROVIDERS.get(name)
	if not provider_cls:
		raise ValueError(
			f"Unknown provider: '{name}'. Available: {list(PROVIDERS.keys())}"
		)
	return provider_cls()
