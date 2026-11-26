from abc import ABC, abstractmethod

from models import FlightItinerary, FlightSearchQuery


class BaseFlightProvider(ABC):
	"""Abstract base class for all flight data providers."""

	@property
	@abstractmethod
	def name(self) -> str:
		"""Unique identifier name for this provider (e.g. 'fast-flights', 'amadeus')."""
		pass

	@abstractmethod
	def search(self, query: FlightSearchQuery) -> list[FlightItinerary]:
		"""Search for flights given the search query parameters and return uniform FlightItinerary models."""
		pass
