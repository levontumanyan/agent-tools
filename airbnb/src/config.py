import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project paths
ROOT_DIR = Path(__file__).parent.parent
REPO_DIR = Path.home() / "repos" / "agent-tools" / "airbnb"
if (
	not (ROOT_DIR / "benchmarks.json").exists()
	and (REPO_DIR / "benchmarks.json").exists()
):
	ROOT_DIR = REPO_DIR

BENCHMARKS_PATH = ROOT_DIR / "benchmarks.json"
SEARCH_FILTERS_PATH = ROOT_DIR / "search_filters.json"
AMENITIES_PATH = ROOT_DIR / "amenities.json"

# Cache paths
CACHE_DIR = ROOT_DIR / ".cache"
LISTING_CACHE = CACHE_DIR / "listings"
CITY_CACHE = CACHE_DIR / "cities.json"
CLIMATE_CACHE = CACHE_DIR / "climate.json"

# Logging paths
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

# Reports path
REPORTS_DIR = ROOT_DIR / "reports"

# Ensure directories exist
LISTING_CACHE.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Test Data (for caching and integration tests)
TEST_DATA_DIR = ROOT_DIR / "tests" / "data"
TEST_LISTING_ID = "19643333"

# API Keys & Auth
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AIRBNB_COOKIE = os.getenv("AIRBNB_COOKIE")
COOKIE_FILE = ROOT_DIR / "cookies.txt"
USER_COOKIE_FILE = Path.home() / ".config" / "airbnb" / "cookies.txt"

if not AIRBNB_COOKIE:
	if COOKIE_FILE.exists():
		try:
			AIRBNB_COOKIE = COOKIE_FILE.read_text(encoding="utf-8").strip()
		except Exception:
			pass
	elif USER_COOKIE_FILE.exists():
		try:
			AIRBNB_COOKIE = USER_COOKIE_FILE.read_text(encoding="utf-8").strip()
		except Exception:
			pass
