import pytest

from src.scorer import Scorer


@pytest.fixture
def benchmarks():
	return {
		"metrics": {
			"value": {
				"weight": 1.0,
				"function": "fixed_decay",
				"params": {"decay_rate": 0.1},
			}
		},
		"penalties": [
			{
				"name": "Low Rating",
				"condition": {"field": "review_score", "operator": "<", "value": 4.5},
				"multiplier": 0.5,
			}
		],
		"hard_filters": {"must_have_amenities": ["wifi"]},
	}


def test_scorer_passes_hard_filters(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1)
	listing = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"price": {"amount": 100},
		"rating": {"guest_satisfaction": 4.8, "review_count": 20},
	}
	score, penalties = scorer.calculate_score(listing)
	assert score > 0
	assert len(penalties) == 0


def test_scorer_fails_hard_filters(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1)
	listing = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": False}]}
		],
		"price": {"amount": 100},
		"rating": {"guest_satisfaction": 4.8, "review_count": 20},
	}
	score, penalties = scorer.calculate_score(listing)
	assert score == 0
	assert any("FAILED: Missing wifi" in p for p in penalties)


def test_scorer_applies_penalty(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1)
	listing = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"price": {"amount": 100},
		"rating": {"guest_satisfaction": 4.0, "review_count": 20},
	}
	# Base score: 100 - (100 * 0.1) = 90
	# Penalty: 90 * 0.5 = 45
	score, penalties = scorer.calculate_score(listing)
	assert score == 45.0
	assert "Low Rating" in penalties


def test_scorer_fast_wifi_requirement_passed(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1, require_fast_wifi=True)
	listing = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"highlights": [
			{"title": "Fast wifi", "subtitle": "At 100 Mbps, you can take video calls"}
		],
		"price": {"amount": 100},
		"rating": {"guest_satisfaction": 4.8, "review_count": 20},
	}
	score, penalties = scorer.calculate_score(listing)
	assert score > 0
	assert len(penalties) == 0


def test_scorer_fast_wifi_requirement_failed(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1, require_fast_wifi=True)
	listing = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"highlights": [],
		"price": {"amount": 100},
		"rating": {"guest_satisfaction": 4.8, "review_count": 20},
	}
	score, penalties = scorer.calculate_score(listing)
	assert score == 0
	assert any("FAILED: Missing verified fast wifi" in p for p in penalties)


def test_scorer_keyword_analysis_with_reviews(benchmarks):
	scorer = Scorer(benchmarks, num_nights=1)
	listing = {
		"reviews": [
			{"comments": "Very clean and quiet, excellent fast wifi!"},
			{"comments": "Great place with a nice desk to work."},
		]
	}
	score = scorer._keyword_analysis(
		listing,
		{
			"positive_keywords": ["clean", "quiet", "fast wifi", "desk"],
			"negative_keywords": ["loud", "dirty"],
		},
	)
	assert score > 80.0


def test_extract_review_evidence(benchmarks):
	scorer = Scorer(benchmarks)
	listing = {
		"reviews": [
			{"comments": "The wifi was fast and zoom calls were flawless."},
			{"comments": "The street was very noisy and loud at night."},
			{
				"comments": "We cooked every day in the well-equipped kitchen with a great oven."
			},
		]
	}
	evidence = scorer.extract_review_evidence(listing)
	assert len(evidence["wifi_positive"]) == 1
	assert "wifi was fast" in evidence["wifi_positive"][0]
	assert len(evidence["noise_negative"]) == 1
	assert "noisy" in evidence["noise_negative"][0]
	assert len(evidence["kitchen_positive"]) == 1
	assert "cooked every day" in evidence["kitchen_positive"][0]


def test_scorer_missing_ac_penalty_and_flag():
	bm = {
		"metrics": {
			"value": {
				"weight": 1.0,
				"function": "fixed_decay",
				"params": {"decay_rate": 0.0},
			}
		},
		"penalties": [
			{
				"id": "missing_ac",
				"name": "Missing Air Conditioning",
				"type": "missing_amenity",
				"amenity": "ac",
				"multiplier": 0.90,
				"flag": "[FLAG: No AC]",
			}
		],
		"hard_filters": {},
	}
	scorer = Scorer(bm)
	# Listing without AC
	listing = {
		"amenities": [
			{"title": "Heating", "values": [{"title": "Heating", "available": True}]}
		],
		"price": {"amount": 50},
	}
	res = scorer.calculate_score(listing)
	assert res[0] == 90.0  # 100 * 0.90
	assert any("Missing Air Conditioning" in p for p in res[1])
	assert "[FLAG: No AC]" in res.flags


def test_scorer_inadequate_kitchen_penalty():
	bm = {
		"metrics": {
			"value": {
				"weight": 1.0,
				"function": "fixed_decay",
				"params": {"decay_rate": 0.0},
			}
		},
		"penalties": [
			{
				"id": "inadequate_kitchen",
				"name": "Inadequate Kitchen (Kitchenette/No Stove)",
				"type": "kitchen_tier",
				"disallowed_tiers": ["kitchenette", "no_kitchen"],
				"multiplier": 0.65,
				"flag": "[FLAG: Inadequate Kitchen]",
			}
		],
		"hard_filters": {},
	}
	scorer = Scorer(bm)
	# Listing with only microwave (kitchenette)
	listing = {
		"amenities": [
			{
				"title": "Kitchen",
				"values": [
					{"title": "Kitchen", "available": True},
					{"title": "Microwave", "available": True},
				],
			}
		],
		"price": {"amount": 50},
	}
	res = scorer.calculate_score(listing)
	assert res[0] == 65.0  # 100 * 0.65
	assert any("Inadequate Kitchen" in p for p in res[1])
	assert "[FLAG: Inadequate Kitchen]" in res.flags
	assert "[FLAG: Kitchenette Only / No Stove or Oven]" in res.flags


def test_scorer_bonus_amenities_ac_matches_spaces():
	bm = {
		"metrics": {
			"amenities": {
				"weight": 1.0,
				"function": "percentage_match",
				"params": {
					"bonus_amenities": [
						"air_conditioning",
						"dedicated_workspace",
					]
				},
			}
		},
		"penalties": [],
		"hard_filters": {},
	}
	scorer = Scorer(bm)
	# Listing has "Air conditioning" with a space and "Dedicated workspace" with a space
	listing = {
		"amenities": [
			{
				"title": "Cooling",
				"values": [{"title": "Air conditioning", "available": True}],
			},
			{
				"title": "Office",
				"values": [{"title": "Dedicated workspace", "available": True}],
			},
		]
	}
	score, penalties = scorer.calculate_score(listing)
	assert score == 100.0  # Both 2/2 matched!


def test_scorer_market_relative_pricing():
	bm = {
		"metrics": {
			"value": {
				"weight": 1.0,
				"function": "market_relative",
				"params": {"target_ratio": 0.8, "base_ratio": 1.0},
			}
		},
		"penalties": [],
		"hard_filters": {},
	}
	# Market median is $50/night
	scorer = Scorer(bm, num_nights=1, market_median_price=50.0)

	# Bargain listing: $35/night (ratio 0.70 <= 0.80) -> 100 pts
	listing_cheap = {"price": {"amount": 35.0, "nightly": 35.0}}
	assert scorer.calculate_score(listing_cheap)[0] == 100.0

	# Fair market listing: $50/night (ratio 1.0) -> 80 pts
	listing_fair = {"price": {"amount": 50.0, "nightly": 50.0}}
	assert scorer.calculate_score(listing_fair)[0] == 80.0

	# Pricey listing: $75/night (ratio 1.5) -> 40 pts
	listing_pricey = {"price": {"amount": 75.0, "nightly": 75.0}}
	assert scorer.calculate_score(listing_pricey)[0] == 40.0


def test_scorer_single_listing_ignores_price():
	bm = {
		"metrics": {
			"amenities": {
				"weight": 0.6,
				"function": "percentage_match",
				"params": {"bonus_amenities": ["wifi"]},
			},
			"value": {
				"weight": 0.4,
				"function": "market_relative",
				"params": {},
			},
		},
		"penalties": [],
		"hard_filters": {},
	}
	# Single listing inspection has market_median_price=None
	scorer = Scorer(bm, market_median_price=None)

	listing_cheap = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"price": {"amount": 20.0, "nightly": 20.0},
	}
	listing_expensive = {
		"amenities": [
			{"title": "Internet", "values": [{"title": "Wifi", "available": True}]}
		],
		"price": {"amount": 5000.0, "nightly": 5000.0},
	}

	score_cheap = scorer.calculate_score(listing_cheap)[0]
	score_expensive = scorer.calculate_score(listing_expensive)[0]

	# Because market_median_price is None, price is ignored and weights are re-normalized
	assert score_cheap == 100.0
	assert score_expensive == 100.0
	assert score_cheap == score_expensive


def test_detect_noise_profile(benchmarks):
	scorer = Scorer(benchmarks)

	# 1. Soundproof windows in description
	listing_soundproof = {
		"title": "Apartment with double-pane windows",
		"description": "Quiet retreat featuring termoacústico windows.",
		"reviews": [],
	}
	profile = scorer.detect_noise_profile(listing_soundproof)
	assert profile["soundproof_windows"] is True
	assert "[FEATURE: Soundproof Windows]" in profile["flags"]
	assert profile["has_risk"] is False

	# 2. Host noise warning in description
	listing_noisy_desc = {
		"description": "Note: busy street with some street noise.",
		"reviews": [],
	}
	profile_noisy = scorer.detect_noise_profile(listing_noisy_desc)
	assert profile_noisy["has_risk"] is True
	assert "[FLAG: Noise Risk]" in profile_noisy["flags"]

	# 3. Guest reviews complain about noise
	listing_noisy_reviews = {
		"description": "Cozy place.",
		"reviews": [{"comments": "Very loud traffic all night and honking."}],
	}
	profile_noisy_rev = scorer.detect_noise_profile(listing_noisy_reviews)
	assert profile_noisy_rev["has_risk"] is True
	assert "[FLAG: Noise Risk]" in profile_noisy_rev["flags"]

	# 4. Verified quiet reviews
	listing_quiet = {
		"description": "Peaceful home.",
		"reviews": [
			{"comments": "Super quiet neighborhood, slept wonderfully."},
			{"comments": "Very peaceful and tranquil stay."},
		],
	}
	profile_quiet = scorer.detect_noise_profile(listing_quiet)
	assert profile_quiet["verified_quiet"] is True
	assert "[SIGNAL: Verified Quiet]" in profile_quiet["flags"]
	assert profile_quiet["has_risk"] is False


def test_review_recency_weighting(benchmarks):
	scorer = Scorer(benchmarks)

	# Recent review (< 12 months)
	r_recent = {"createdAt": "2026-09-01T12:00:00Z", "comments": "Great place"}
	w_recent, label_recent = scorer._parse_review_recency_weight(r_recent)
	assert w_recent == 1.0

	# Older review (1-2 years ago)
	r_old = {"createdAt": "2025-05-01T12:00:00Z", "comments": "Decent stay"}
	w_old, label_old = scorer._parse_review_recency_weight(r_old)
	assert w_old == 0.5

	# Ancient review (> 2 years ago)
	r_ancient = {"createdAt": "2023-01-01T12:00:00Z", "comments": "Old stay"}
	w_ancient, label_ancient = scorer._parse_review_recency_weight(r_ancient)
	assert w_ancient == 0.2


def test_review_supersession_wifi(benchmarks):
	scorer = Scorer(benchmarks)

	# Listing had slow wifi 2 years ago, but recently got fiber verified
	listing = {
		"description": "Lovely studio with 1000mbps fiber optic internet.",
		"reviews": [
			{
				"createdAt": "2023-01-10T10:00:00Z",
				"comments": "The wifi was bad wifi and slow wifi.",
			},
			{
				"createdAt": "2026-10-01T10:00:00Z",
				"comments": "Internet was super fast, flawless video calls.",
			},
		],
	}

	evidence = scorer.extract_review_evidence(listing)
	# Historical negative wifi review should be superseded by the recent fiber verification
	assert len(evidence["wifi_negative"]) == 0
	assert len(evidence["wifi_positive"]) >= 1


def test_climate_aware_comfort_scoring():
	bm = {
		"metrics": {
			"value": {
				"weight": 1.0,
				"function": "fixed_decay",
				"params": {"decay_rate": 0.0},
			}
		},
		"penalties": [
			{
				"id": "missing_ac",
				"name": "Missing Air Conditioning",
				"type": "missing_amenity",
				"amenity": "ac",
				"multiplier": 0.90,
				"flag": "[FLAG: No AC]",
			}
		],
		"hard_filters": {},
	}

	# 1. Mild/Temperate climate (Arequipa in Nov) where AC is not needed
	scorer_mild = Scorer(bm, check_in="2026-11-11", check_out="2026-12-09")
	listing_no_ac_mild = {
		"coordinates": {"latitude": -16.409, "longitude": -71.537},
		"amenities": [],
		"price": {"amount": 50},
	}
	res_mild = scorer_mild.calculate_score(listing_no_ac_mild)
	# Should NOT penalize for missing AC in mild climate!
	assert "[INFO: Mild Climate (AC Optional)]" in res_mild.flags
	assert not any("Missing Air Conditioning" in p for p in res_mild.penalties)
	# Heating flagged in chilly night climate
	assert "[FLAG: No Heating (Cold Nights)]" in res_mild.flags

	# 2. Hot climate (Lima in Feb) where AC is needed
	scorer_hot = Scorer(bm, check_in="2026-02-01", check_out="2026-02-28")
	listing_no_ac_hot = {
		"coordinates": {"latitude": -12.12, "longitude": -77.01},
		"amenities": [],
		"price": {"amount": 50},
	}
	res_hot = scorer_hot.calculate_score(listing_no_ac_hot)
	# SHOULD penalize for missing AC in hot summer
	assert "[FLAG: No AC]" in res_hot.flags
	assert any("Missing Air Conditioning" in p for p in res_hot.penalties)
