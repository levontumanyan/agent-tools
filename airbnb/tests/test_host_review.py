import json

from src.fetcher import get_host_listings, resolve_host
from src.host_review import (
	analyze_host_reviews,
	detect_visitor_restriction,
	extract_review_text,
	format_host_report,
)


def test_resolve_host_numeric():
	res = resolve_host("482816256")
	assert res == {"host_id": "482816256", "host_name": None, "resolved_room_id": None}


def test_resolve_host_from_room_url(mocker):
	mocker.patch(
		"src.fetcher.get_listing_details",
		return_value={"host": {"id": "482816256", "name": "Premium Bed"}},
	)
	res = resolve_host("https://www.airbnb.ca/rooms/743960622725398679")
	assert res == {
		"host_id": "482816256",
		"host_name": "Premium Bed",
		"resolved_room_id": "743960622725398679",
	}


def test_resolve_host_from_h_redirect(mocker):
	mock_session = mocker.MagicMock()
	mock_resp = mocker.MagicMock()
	mock_resp.status_code = 302
	mock_resp.headers = {"location": "/rooms/743960622725398679"}
	mock_session.get.return_value = mock_resp

	mocker.patch("src.fetcher._get_session", return_value=mock_session)
	mocker.patch(
		"src.fetcher.get_listing_details",
		return_value={"host": {"id": "482816256", "name": "Premium Bed"}},
	)

	res = resolve_host("https://www.airbnb.ca/h/premium-bed-by-olvia-full-equipped-2")
	assert res == {
		"host_id": "482816256",
		"host_name": "Premium Bed",
		"resolved_room_id": "743960622725398679",
	}


def test_resolve_host_login_redirect_returns_none(mocker):
	mock_session = mocker.MagicMock()
	mock_resp = mocker.MagicMock()
	mock_resp.status_code = 302
	mock_resp.headers = {
		"location": "https://www.airbnb.ca/login?redirect_url=/users/profile/1483760065797291342"
	}
	mock_session.get.return_value = mock_resp

	mocker.patch("src.fetcher._get_session", return_value=mock_session)
	assert resolve_host("https://www.airbnb.ca/h/some-gated-host") is None


def test_get_host_listings(mocker):
	mocker.patch("src.fetcher.pyairbnb.api.get", return_value="test_key")
	mock_get = mocker.patch(
		"src.fetcher.pyairbnb.host.get_listings_from_user",
		return_value=[{"id": "111", "reviewCount": "5"}],
	)
	res = get_host_listings("482816256")
	assert res == [{"id": "111", "reviewCount": "5"}]
	mock_get.assert_called_once_with(482816256, "test_key", "")


def test_extract_review_text_prefers_localized():
	rev = {
		"comments": "Excelente servicio.<br/>Muy limpio.",
		"localizedReview": {"comments": "Excellent service.<br/>Very clean."},
	}
	assert extract_review_text(rev) == "Excellent service. Very clean."
	assert (
		extract_review_text({"comments": "Great place<br/>Quiet"})
		== "Great place Quiet"
	)


def test_detect_visitor_restriction():
	restricted_details = {
		"house_rules": {
			"aditional": "No visitors allowed after 10pm.",
			"general": [],
		}
	}
	assert detect_visitor_restriction(restricted_details) == (
		True,
		"No visitors allowed after 10pm.",
	)

	spanish_details = {
		"house_rules": {
			"aditional": "",
			"general": [
				{
					"title": "During your stay",
					"values": [{"title": "No se permiten visitas"}],
				}
			],
		}
	}
	assert detect_visitor_restriction(spanish_details) == (
		True,
		"No se permiten visitas",
	)

	ok_details = {
		"house_rules": {
			"aditional": "Please turn off AC when leaving.",
			"general": [
				{"title": "During your stay", "values": [{"title": "No smoking"}]}
			],
		}
	}
	assert detect_visitor_restriction(ok_details) == (False, None)


def test_analyze_and_format_host_reviews():
	meta = [
		{
			"id": "741283577094663788",
			"nameOrPlaceholderName": "Wifi(80Mbps)all new, self check-in #1",
			"ratingAverage": 4.93,
			"reviewCount": "2",
			"localizedRoomType": "Entire home/apt",
		},
		{
			"id": "733557563871740050",
			"nameOrPlaceholderName": "Wifi(80Mbps), all new, self check-in #2",
			"ratingAverage": 4.0,
			"reviewCount": "1",
			"localizedRoomType": "Entire home/apt",
		},
	]
	details_by_id = {
		"741283577094663788": {
			"person_capacity": 4,
			"exact_price": {
				"amount": 1400.0,
				"nightly": 50.0,
				"orig_amount": 1600.0,
				"discount_pct": 12.5,
				"currency": "CAD",
			},
			"house_rules": {"aditional": "", "general": []},
			"reviews": [
				{
					"rating": 5,
					"createdAt": "2026-11-06T15:44:28Z",
					"localizedDate": "2 weeks ago",
					"reviewer": {"firstName": "Rodolfo"},
					"comments": "The host was very kind and clean space.",
				},
				{
					"rating": 3,
					"createdAt": "2025-08-02T20:24:53Z",
					"localizedDate": "August 2025",
					"reviewer": {"firstName": "Jay"},
					"comments": "Construction noise ruined my stay, though host was responsive.",
				},
			],
		},
		"733557563871740050": {
			"person_capacity": 6,
			"exact_price": None,
			"house_rules": {
				"aditional": "Only registered guests allowed.",
				"general": [],
			},
			"reviews": [
				{
					"rating": 4,
					"createdAt": "2026-01-10T12:00:00Z",
					"localizedDate": "January 2026",
					"reviewer": {"firstName": "Ana"},
					"localizedReview": {
						"comments": "Good stay, had a brief power outage."
					},
					"comments": "Buena estadia, hubo un apagon.",
				}
			],
		},
	}

	report = analyze_host_reviews(
		host_id="482816256",
		host_name="Premium Bed",
		host_listings_meta=meta,
		details_by_id=details_by_id,
		check_in="2027-01-10",
		check_out="2027-02-07",
		adults=1,
		currency="CAD",
	)

	assert report["total_reviews_fetched"] == 3
	assert report["total_reviews_expected"] == 3
	assert report["rating_distribution"] == {"5": 1, "4": 1, "3": 1, "2": 0, "1": 0}
	assert report["date_range"] == {"earliest": "2025-08-02", "latest": "2026-11-06"}
	assert report["listings"][0]["url"] == (
		"https://www.airbnb.ca/rooms/741283577094663788?check_in=2027-01-10&check_out=2027-02-07&adults=1"
	)
	assert report["listings"][1]["visitor_restricted"] is True
	assert "[FLAG: Visitors Restricted]" in report["listings"][1]["flags"]

	text = format_host_report(report)
	assert "CAD $1400.00 total ($50.00/nt" in text
	assert "[FLAG: Visitors Restricted]" in text
	assert (
		"https://www.airbnb.ca/rooms/741283577094663788?check_in=2027-01-10&check_out=2027-02-07&adults=1"
		in text
	)
	assert "Responsive / helpful host" in text
	assert "Noise / construction" in text
	assert "Power / electricity outages" in text

	# Ensure JSON serializability
	dumped = json.dumps(report)
	assert "Premium Bed" in dumped
