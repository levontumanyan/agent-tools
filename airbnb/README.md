# Airbnb Benchmarker

A Python-based tool to search, scrape, and score Airbnb listings based on custom benchmarks and sentiment analysis of guest reviews.

# Features
- **Search**: Automated search based on price range and location.
- **Scrape**: Pulls listing descriptions, amenities, and the last 50+ reviews.
- **Multimodal Scoring**:
	- Sentiment analysis on reviews (NLP).
	- Visual verification of amenities via image analysis (LLM).
- **Custom Benchmarking**: Score listings based on weighted criteria (e.g., cleanliness > price).

# Scoring Methodology

The scoring system calculates a final score out of 100 based on a two-step process: **Base Scores** and **Penalties**.

### 1. Base Score (Metrics)
Listings are evaluated against a set of configurable metrics (e.g., Amenities, Value, Sentiment). Each metric uses a specific function (like `percentage_match` or `price_to_market_average`) to generate a score from 0-100. This score is then multiplied by its assigned weight. The sum of all weighted metrics forms the Base Score.

$$Base\ Score = \sum (Metric\ Score_i \times Weight_i)$$

### 2. Apply Penalties (Multipliers)
Penalties are applied to heavily punish listings that fail to meet critical quality thresholds without outright disqualifying them. A penalty acts as a multiplier (e.g., `0.5x`) on the Base Score.

For example, if a listing achieves a Base Score of 85 but has fewer than 10 reviews, a `0.5` penalty is applied:
$$Final\ Score = 85 \times 0.5 = 42.5$$

Multiple penalties can stack. For instance, low review count (0.5x) AND low review score (0.5x) would reduce an 85 to 21.25.

# Setup

1. Clone the repository.
2. Install dependencies:
3. Configure your `.env` with:
	- `GEMINI_API_KEY`

# Usage

```bash
# Default search (Montreal, prices in CAD)
airbnb

# Search specific location and price range (CAD)
airbnb --location "Miraflores, Peru" --min_price 20 --max_price 30

# Long stay search with dates and rating filters
airbnb --location "San Borja, Lima, Peru" --check_in 2026-10-10 --check_out 2026-11-07 --min_price 700 --max_price 1600 --limit 15

# Multi-city market survey
airbnb --survey --cities "Lima, Peru;Santiago, Chile" --check_in 2026-10-10 --check_out 2026-11-07
```

# Architecture Overview

1.  **Extraction**: Use `pyairbnb` to fetch listing metadata and reviews.
2.  **Scoring Engine**:
		* **Reviews**: Use an LLM (via Gemini API) or a lexicon-based tool like `vivid_astronaut` to perform sentiment analysis and extract specific features (e.g., "mentions noise," "cleanliness").
		* **Description/Images**: Use Gemini 1.5 Flash/Pro for multimodal analysis—pass the listing description and image URLs to verify if the "pool" is a kiddie pool or if the "office" is just a kitchen chair.
3.  **Output**: A sorted list (CSV or JSON) based on a weighted formula of your benchmarks.

---

# Project TODO List

## caching

- are ids the same across different searches. does the same listing have the same id all the time.
- how do we dump a listing by its id and cache it.

## Phase 1: Data Acquisitio- [ ] Initialize repository and virtual environment.

- [ ] Implement `pyairbnb` search function to return listing IDs within a price range.
- [ ] Create a module to fetch full review text and listing descriptions for a given ID.
- [ ] Handle rate limiting/proxies to avoid IP bans.

## Phase 2: Analysis Engine

- [ ] Integrate Gemini API for text-based sentiment analysis.
- [ ] Define "Benchmark Weights" (e.g., `Review_Sentiment: 0.5`, `Price_Score: 0.3`, `Amenity_Match: 0.2`).
- [ ] **Multimodal Step**: Pass listing photo URLs to Gemini to confirm specific requirements (e.g., "Does the desk have an ergonomic chair?").

## Phase 3: Scoring & UI

- [ ] Build the scoring logic $Score = \sum (weight_i \times metric_i)$.
- [ ] Implement a local storage solution (SQLite or JSON) to cache results.
- [ ] Create a CLI or simple Streamlit dashboard to display the ranked list.

## Phase 4: Refinement

- [ ] Add "Red Flag" detection (e.g., keywords like "construction," "loud," "smoke").
- [ ] Export final recommendations to CSV/Excel.

# todo

- [ ] add guest favourite to be heavily encouraged
- [ ] superhost same
- [ ] high speed wifi heavilyyyyyyy
- [ ] Host details
  - [ ] Response rate: 60% (BAD)
  - [ ] Responds within a day (BAD)
- [ ] make sure that network errors do not trip us out.
- [ ] **Implement Proxy Support**: Add support for `proxy_url` to bypass rate limiting and investigate regional pricing/tax differences.
	- **Why**: Allows processing 100+ listings without IP bans and lets us see "local" pricing/taxes by appearing in different countries.
	- **Steps**:
		1. Add `PROXY_URL` to `.env` and `src/config.py`.
		2. Add `--proxy` flag to `src/main.py` CLI.
		3. Update `src/fetcher.py` to pass the proxy to `pyairbnb.search_all` and `pyairbnb.get_details`.
- [ ] https://github.com/johnbalvin/pyairbnb/tree/main/src/pyairbnb - can you go through the code and make sure that this is not possible to do with pyairbnb before we do it on our side? also document all the available search/filter options and add in `search_filters.example.json`

---

# Proposed Libraries

* Data Fetching: pyairbnb or requests (if using RapidAPI).
* Multimodal AI: google-generativeai (for Gemini 1.5 Pro/Flash to analyze listing photos and review sentiment).
* Data Validation: pydantic (to ensure listing data matches your scoring schema).
* Caching: diskcache (to avoid re-scraping the same listing and wasting API credits/time).

---

# Rough Project Structure

├── src/
│   ├── fetcher.py     # Logic to search and get listing details/photos
│   ├── main.py        # CLI entry point
│   ├── config.py      # Env vars and path constants
│   ├── utils.py       # Image downloading and caching helpers
│   └── scorer.py      # LLM prompts and scoring math (planned)
├── benchmarks.json    # User-defined weights and "must-haves"
├── Makefile           # Standard commands (test, lint, run)
└── pyproject.toml

# Scoring & Benchmarking Logic

I suggest a weighted scoring system stored in your benchmarks.json. This allows you to tune your "ideal" apartment:

- Sentiment: (NLP/LLM)
  - Reviews must not mention 'noise' or 'loud' more than twice.
- Visuals: Gemini Vision
  - Verify 'dedicated workspace' actually has an ergonomic chair.
Amenities: Boolean Check
  - Must have: AC, High-speed Wifi, Self check-in.
- Value: Math
  - (Price / Average Price in Area) * Weight

# Geocoding

1. Geocoding: We can pass any city name (e.g., --location "Toronto"), and it will find the coordinates through geopy.
2. City Cache: It saves coordinates to .cache/cities.json to avoid repeating the geocoding call.
3. Listing Cache: Detailed listing data is stored in .cache/listings/ for 24 hours.
4. Batch Processing: We are now searching and summarizing the top 5 listings in a city.

# Technical Note: Scoring Logic

To normalize your scoring, you can use a min-max scaling approach for price while using a -1 to 1 sentiment scale for reviews:

$$Final\ Score = (W_s \cdot S_{rev}) + (W_p \cdot \frac{P_{max} - P_{curr}}{P_{max} - P_{min}}) + (W_a \cdot A_{match})$$

Where:
* $W$: Weights for Sentiment, Price, and Amenities.
* $S_{rev}$: Average sentiment score of reviews.
* $P$: Price values.
* $A_{match}$: Boolean/Ratio of required amenities found.

Would you like the Python boilerplate to handle the `pyairbnb` search and review extraction first?
