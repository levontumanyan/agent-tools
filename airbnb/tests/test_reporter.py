import csv
import json

import pytest

from src.reporter import (
	generate_csv_report,
	generate_json_report,
	generate_survey_report,
)


@pytest.fixture
def mock_listings():
	return [
		{
			"id": "A1",
			"score": 85.5,
			"name": "Listing A",
			"price": 100.0,
			"currency": "USD",
			"review_count": 50,
			"rating": 4.8,
			"amenities": 10,
			"penalties": [],
		},
		{
			"id": "B2",
			"score": 92.0,
			"name": "Listing B",
			"price": 150.0,
			"currency": "USD",
			"review_count": 100,
			"rating": 4.9,
			"amenities": 15,
			"penalties": ["Low Review Count"],
		},
	]


def test_generate_new_csv(tmp_path, mock_listings):
	"""Verify that a new CSV is created with correct headers starting on the first row."""
	report_path = tmp_path / "test_report.csv"
	success = generate_csv_report(mock_listings, report_path)

	assert success
	assert report_path.exists()

	with open(report_path, "r", newline="", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		rows = list(reader)

		# Check headers (first row should be headers for DictReader to work like this)
		assert reader.fieldnames == [
			"Rank",
			"Score",
			"Listing ID",
			"Title",
			"Nightly Price",
			"Total Stay Price",
			"Orig Total Price",
			"Discount %",
			"Currency",
			"Bedrooms",
			"Guests",
			"Review Count",
			"Review Rating",
			"Total Amenities",
			"Penalties Applied",
			"Listing URL",
		]

		# Check data
		assert len(rows) == 2
		assert rows[0]["Listing ID"] == "B2"


def test_csv_merging(tmp_path, mock_listings):
	"""Verify that new listings are merged into an existing CSV."""
	report_path = tmp_path / "merge_report.csv"

	# 1. Create initial report
	generate_csv_report(mock_listings, report_path)

	# 2. Merge with new data
	new_data = [
		{
			"id": "C3",
			"score": 99.0,
			"name": "L3",
			"price": 0,
			"currency": "",
			"review_count": 0,
			"rating": 0,
			"amenities": 0,
			"penalties": [],
		}
	]
	generate_csv_report(new_data, report_path)

	with open(report_path, "r", newline="", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		rows = list(reader)
		assert len(rows) == 3
		assert rows[0]["Listing ID"] == "C3"


def test_csv_sorting_logic(tmp_path):
	"""Verify that listings are always sorted by score descending."""
	report_path = tmp_path / "sort_report.csv"
	unsorted_listings = [
		{
			"id": "1",
			"score": 50.0,
			"name": "L1",
			"price": 0,
			"currency": "",
			"review_count": 0,
			"rating": 0,
			"amenities": 0,
			"penalties": [],
		},
		{
			"id": "2",
			"score": 90.0,
			"name": "L2",
			"price": 0,
			"currency": "",
			"review_count": 0,
			"rating": 0,
			"amenities": 0,
			"penalties": [],
		},
		{
			"id": "3",
			"score": 70.0,
			"name": "L3",
			"price": 0,
			"currency": "",
			"review_count": 0,
			"rating": 0,
			"amenities": 0,
			"penalties": [],
		},
	]

	generate_csv_report(unsorted_listings, report_path)

	with open(report_path, "r", newline="", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		scores = [float(row["Score"]) for row in reader]
		assert scores == [90.0, 70.0, 50.0]


def test_generate_new_json(tmp_path, mock_listings):
	"""Verify that a new JSON report is created with correct structure and ranks."""
	report_path = tmp_path / "test_report.json"
	success = generate_json_report(mock_listings, report_path)

	assert success
	assert report_path.exists()

	with open(report_path, "r", encoding="utf-8") as f:
		data = json.load(f)

	assert len(data) == 2
	# Higher score (92.0) should be rank 1
	assert data[0]["id"] == "B2"
	assert data[0]["rank"] == 1
	assert data[0]["score"] == 92.0
	assert data[0]["penalties"] == ["Low Review Count"]
	assert data[0]["url"] == "https://www.airbnb.ca/rooms/B2"

	assert data[1]["id"] == "A1"
	assert data[1]["rank"] == 2


def test_json_merging(tmp_path, mock_listings):
	"""Verify that new listings are merged into an existing JSON report."""
	report_path = tmp_path / "merge_report.json"

	# 1. Create initial report
	generate_json_report(mock_listings, report_path)

	# 2. Merge with new listing
	new_data = [
		{
			"id": "C3",
			"score": 99.0,
			"name": "Listing C",
			"price": 200.0,
			"currency": "USD",
			"review_count": 10,
			"rating": 5.0,
			"amenities": 20,
			"penalties": [],
		}
	]
	generate_json_report(new_data, report_path)

	with open(report_path, "r", encoding="utf-8") as f:
		data = json.load(f)

	assert len(data) == 3
	assert data[0]["id"] == "C3"
	assert data[0]["rank"] == 1
	assert data[0]["score"] == 99.0


def test_json_sorting_logic(tmp_path):
	"""Verify that JSON listings are always sorted by score descending."""
	report_path = tmp_path / "sort_report.json"
	unsorted_listings = [
		{"id": "1", "score": 50.0},
		{"id": "2", "score": 90.0},
		{"id": "3", "score": 70.0},
	]

	generate_json_report(unsorted_listings, report_path)

	with open(report_path, "r", encoding="utf-8") as f:
		data = json.load(f)

	scores = [item["score"] for item in data]
	assert scores == [90.0, 70.0, 50.0]
	ranks = [item["rank"] for item in data]
	assert ranks == [1, 2, 3]


def test_generate_survey_report(tmp_path):
	csv_path = tmp_path / "survey.csv"
	json_path = tmp_path / "survey.json"
	survey_data = [
		{
			"city": "Buenos Aires, Argentina",
			"total_found": 150,
			"qualified_count": 45,
			"median_total": 1500.0,
			"nightly_median": 53.57,
			"p25_total": 1200.0,
			"p75_total": 1800.0,
			"avg_monthly_discount_pct": 25.0,
			"pct_with_discount": 80.0,
			"currency": "CAD",
		}
	]
	generate_survey_report(survey_data, csv_path=csv_path, json_path=json_path)
	assert csv_path.exists()
	assert json_path.exists()

	with open(json_path, "r", encoding="utf-8") as f:
		loaded = json.load(f)
		assert len(loaded) == 1
		assert loaded[0]["city"] == "Buenos Aires, Argentina"
		assert loaded[0]["median_total"] == 1500.0
