from src.config import BENCHMARKS_PATH, CACHE_DIR, ROOT_DIR


def test_root_dir_resolution():
	"""Verify that ROOT_DIR points to the project root (parent of src)."""
	assert ROOT_DIR.exists()
	assert (ROOT_DIR / "src").exists()
	assert (ROOT_DIR / "src" / "config.py").exists()


def test_config_paths():
	"""Verify that secondary paths are correctly derived from ROOT_DIR."""
	assert BENCHMARKS_PATH == ROOT_DIR / "benchmarks.json"
	assert CACHE_DIR == ROOT_DIR / ".cache"
