import json
import logging
from pathlib import Path
from typing import Any

from config import BENCHMARKS_FILE, LOGS_DIR


def setup_logging(verbose: bool = False) -> logging.Logger:
	"""Configures application logging to file and console."""
	logger = logging.getLogger("flights")
	logger.setLevel(logging.DEBUG if verbose else logging.INFO)

	if not logger.handlers:
		# Console handler
		console_handler = logging.StreamHandler()
		console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
		console_format = logging.Formatter(
			"[%(asctime)s] %(levelname)s - %(message)s", datefmt="%H:%M:%S"
		)
		console_handler.setFormatter(console_format)
		logger.addHandler(console_handler)

		# File handler
		log_file = LOGS_DIR / "flights.log"
		file_handler = logging.FileHandler(log_file, encoding="utf-8")
		file_handler.setLevel(logging.DEBUG)
		file_format = logging.Formatter(
			"%(asctime)s [%(levelname)s] %(name)s: %(message)s"
		)
		file_handler.setFormatter(file_format)
		logger.addHandler(file_handler)

	return logger


def load_benchmarks(file_path: Path = BENCHMARKS_FILE) -> dict[str, Any]:
	"""Loads benchmarking rules, metrics, and penalties from JSON."""
	if not file_path.exists():
		return {"metrics": {}, "penalties": [], "hard_filters": {}}

	with open(file_path, "r", encoding="utf-8") as f:
		return json.load(f)
