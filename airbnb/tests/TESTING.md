# Testing Strategy - Airbnb Benchmarker

This document outlines the testing strategy for the Airbnb Benchmarker project. Our goal is to ensure the reliability of listing searches, data extraction, and scoring logic while minimizing external API dependencies through mocking.

# Unit Tests

## 1.1 `src/utils.py`
- **Geocoding Success:** Mock `geopy.geocoders.Nominatim` to return a fixed coordinate set. Verify that `get_city_coords` returns the expected dictionary structure.
- **Cache Retrieval:** Mock `CITY_CACHE` to exist with pre-defined data. Verify that `get_city_coords` returns this data directly without calling the geocoder.
- **Error Handling:** Verify the function returns `None` gracefully when the geocoder finds no results.

## 1.2 `src/fetcher.py`
- **Cache Hit:** Mock `LISTING_CACHE` to contain a recent JSON file. Verify that `get_listing_details` returns the file content and does not call `pyairbnb.get_details`.
- **Cache Miss / Expiry:** Mock the cache file to be older than 24 hours. Verify that `pyairbnb.get_details` is called and the new data is saved.
- **Search Logic:** Mock `pyairbnb.search_all` to verify that `search_listings` correctly formats dates and passes bounding box coordinates.

## 1.3 `src/config.py`
- **Path Resolution:** Verify that `ROOT_DIR` correctly identifies the project root and that `BENCHMARKS_PATH` and `CACHE_DIR` are located where expected.

# Integration Tests

## 2.1 CLI Validation (`main.py`)
- **Argument Parsing:** Use `pytest` to mock `sys.argv` and verify that `main()` correctly captures the location, min_price, and max_price.
- **Workflow Execution:** Mock `get_city_coords` and `search_listings` to verify that `main()` follows the logic of: *Geocode -> Search -> Print Top 5 Details*.

# 3. Testing Tools

- **Framework:** `pytest`
- **Mocking:** `pytest-mock` (mocker fixture)
- **Environment:** Run tests via `make test` or `uv run pytest`.

## 4. Best Practices

- **No Network Calls:** All external APIs (pyairbnb, geopy) must be mocked.
- **Deterministic Paths:** Use `pytest`'s `tmp_path` fixture for any file-based tests (e.g., testing the cache) to avoid cluttering the real `.cache` directory.
