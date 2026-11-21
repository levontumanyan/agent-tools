"""
Guard the local pyairbnb runtime patches against silent loss or upstream drift.

The local tool layers personal patches on top of the upstream pyairbnb package
at import time (fetcher.py). Upgrades swap the package in the venv; they can
never clobber these patches, but they can change the symbols being patched or
alter behavior expectations. This test fails loudly if any patch stops applying
or drifts from its documented contract, so `uv lock --upgrade-package pyairbnb`
followed by `make test` is a safe upgrade check.
"""

from importlib.metadata import version

import pyairbnb.api
import pyairbnb.price
import pyairbnb.start

import src.fetcher as fetcher


def test_api_get_runs_pure_upstream():
	"""No local api.get patch: upstream (>=2.2.8, PR #73) owns the fallback key path."""
	assert pyairbnb.api.get.__module__ == "pyairbnb.api"


def test_perf_stubs_are_applied():
	"""Calendar and host-details fetches must stay stubbed out (perf fast-path)."""
	assert pyairbnb.start.get_calendar("") == {}
	assert pyairbnb.start.host_details.get("") == {}


def test_price_endpoint_is_canadian():
	"""Price quotes must come from airbnb.ca (matches the airbnb.ca page prices)."""
	assert pyairbnb.price.BASE_URL == "https://www.airbnb.ca/api/v3/StaysPdpSections"


def test_price_hash_seed_is_valid_sha256():
	"""The seeded persisted-query hash must be a 64-char sha256 hex string."""
	assert len(pyairbnb.price.PERSISTED_QUERY_HASH) == 64
	int(pyairbnb.price.PERSISTED_QUERY_HASH, 16)


def test_details_patch_is_applied():
	"""details.get must be the authenticated local variant (cookie + enhanced parsing)."""
	assert pyairbnb.details.get.__name__ == "_authenticated_details_get"


def test_reviews_run_pure_upstream():
	"""No local reviews patch: upstream (>=2.2.7) owns the hash-rotation fix."""
	assert "get_from_offset" not in [
		n for n in dir(fetcher) if n.startswith("_reviews")
	]


def test_upstream_floor_is_respected():
	"""Upstream must be new enough to carry PRs #70-#74 (price, reviews, api key, details fallbacks)."""
	major, minor, patch = (int(x) for x in version("pyairbnb").split("."))
	assert (major, minor, patch) >= (2, 2, 8)
