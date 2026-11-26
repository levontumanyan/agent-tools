import os
import tempfile
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_DIR = Path.home() / "repos" / "agent-tools" / "flights"
if (
	not (PROJECT_ROOT / "benchmarks.json").exists()
	and (REPO_DIR / "benchmarks.json").exists()
):
	PROJECT_ROOT = REPO_DIR
SRC_DIR = PROJECT_ROOT / "src"
CACHE_DIR = PROJECT_ROOT / ".cache"
FLIGHTS_CACHE_DIR = CACHE_DIR / "flights"
REPORTS_DIR = PROJECT_ROOT / "reports"
LOGS_DIR = Path(tempfile.gettempdir()) / "flights-logs"
BENCHMARKS_FILE = PROJECT_ROOT / "benchmarks.json"

# Ensure runtime directories exist (ignore read-only/sandbox permission errors)
for _dir in (FLIGHTS_CACHE_DIR, REPORTS_DIR, LOGS_DIR):
	try:
		_dir.mkdir(parents=True, exist_ok=True)
	except OSError:
		pass

# Cache Settings
CACHE_TTL_HOURS = int(os.getenv("FLIGHTS_CACHE_TTL_HOURS", "3"))

# Defaults
DEFAULT_CURRENCY = os.getenv("FLIGHTS_CURRENCY", "CAD")
DEFAULT_PROVIDER = "fast-flights"
DEFAULT_TRIP_TYPE = "one-way"
DEFAULT_SEAT_CLASS = "economy"
