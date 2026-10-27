"""Unit tests for the Amenity Registry and Kitchen Evaluation module."""

from src.amenities import (
	evaluate_kitchen,
	get_search_id,
	has_amenity,
)


def test_get_search_id():
	assert get_search_id("ac") == 5
	assert get_search_id("air_conditioning") == 5
	assert get_search_id("kitchen") == 8
	assert get_search_id("washer") == 33
	assert get_search_id("unknown_xyz") is None


def test_has_amenity_by_title_case_and_aliases():
	listing = {
		"amenities": [
			{
				"title": "Heating and cooling",
				"values": [
					{"title": "Central air conditioning", "available": True},
					{"title": "Heating", "available": True},
				],
			},
			{
				"title": "Office",
				"values": [
					{"title": "Dedicated workspace", "available": True},
				],
			},
		]
	}
	assert has_amenity(listing, "ac") is True
	assert has_amenity(listing, "air_conditioning") is True
	assert has_amenity(listing, "dedicated_workspace") is True
	assert has_amenity(listing, "washer") is False


def test_has_amenity_by_system_icon():
	listing = {
		"amenities": [
			{
				"title": "Cooling",
				"values": [
					{
						"title": "Climatiseur",
						"icon": "SYSTEM_SNOWFLAKE",
						"available": True,
					}
				],
			}
		]
	}
	assert has_amenity(listing, "ac") is True


def test_has_amenity_ignores_unavailable():
	listing = {
		"amenities": [
			{
				"title": "Not included",
				"values": [
					{"title": "Air conditioning", "available": False},
					{"title": "Kitchen", "available": False},
				],
			}
		]
	}
	assert has_amenity(listing, "ac") is False
	assert has_amenity(listing, "kitchen") is False


def test_evaluate_kitchen_full():
	listing = {
		"amenities": [
			{
				"title": "Kitchen and dining",
				"values": [
					{"title": "Kitchen", "available": True},
					{"title": "Stove", "available": True},
					{"title": "Oven", "available": True},
					{"title": "Refrigerator", "available": True},
					{"title": "Cooking basics", "available": True},
				],
			}
		]
	}
	res = evaluate_kitchen(listing)
	assert res["tier"] == "full_kitchen"
	assert "[FLAG: No Oven]" not in res["flags"]
	assert "[FLAG: Kitchenette Only / No Stove or Oven]" not in res["flags"]


def test_evaluate_kitchen_kitchenette():
	listing = {
		"amenities": [
			{
				"title": "Kitchen and dining",
				"values": [
					{"title": "Kitchen", "available": True},
					{"title": "Microwave", "available": True},
				],
			}
		]
	}
	res = evaluate_kitchen(listing)
	assert res["tier"] == "kitchenette"
	assert "[FLAG: Kitchenette Only / No Stove or Oven]" in res["flags"]


def test_evaluate_kitchen_no_kitchen():
	listing = {"amenities": []}
	res = evaluate_kitchen(listing)
	assert res["tier"] == "no_kitchen"
	assert "[FLAG: No Kitchen]" in res["flags"]


def test_oven_excludes_microwave():
	listing_microwave = {
		"amenities": [
			{
				"title": "Kitchen",
				"values": [
					{"title": "Horno de microondas", "available": True},
					{"title": "Microwave oven", "available": True},
				],
			}
		]
	}
	assert has_amenity(listing_microwave, "oven") is False


def test_regional_latin_american_terms():
	listing_latam = {
		"amenities": [
			{
				"title": "Cocina",
				"values": [
					{"title": "Anafe eléctrico", "available": True},
					{"title": "Heladera con freezer", "available": True},
				],
			},
			{
				"title": "Espacio",
				"values": [
					{"title": "Espacio de trabajo exclusivo", "available": True},
					{"title": "Minisplit", "available": True},
				],
			},
		]
	}
	assert has_amenity(listing_latam, "stove") is True
	assert has_amenity(listing_latam, "refrigerator") is True
	assert has_amenity(listing_latam, "dedicated_workspace") is True
	assert has_amenity(listing_latam, "ac") is True


def test_has_amenity_description_fallback():
	listing_desc = {
		"amenities": [],
		"description": "Hermoso departamento. Cuenta con estufa a gas, refrigerador grande y escritorio para trabajar.",
	}
	assert has_amenity(listing_desc, "stove", check_description=True) is True
	assert has_amenity(listing_desc, "refrigerator", check_description=True) is True
	assert (
		has_amenity(listing_desc, "dedicated_workspace", check_description=True) is True
	)


def test_evaluate_kitchen_no_refrigerator_not_full():
	listing = {
		"amenities": [
			{
				"title": "Kitchen and dining",
				"values": [
					{"title": "Kitchen", "available": True},
					{"title": "Stove", "available": True},
					{"title": "Oven", "available": True},
					{"title": "Cooking basics", "available": True},
				],
			}
		]
	}
	res = evaluate_kitchen(listing)
	assert res["tier"] == "standard_kitchen"
	assert "[FLAG: No Refrigerator]" in res["flags"]
