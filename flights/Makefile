.PHONY: run lint format test check clean-cache clean

from ?= YUL
to ?= CDG
date ?=
return_date ?=
currency ?= CAD
seat ?= economy
provider ?= fast-flights
limit ?= 15
max_stops ?=
max_price ?=
csv ?=
json ?=
force_refresh ?=
verbose ?=

run:
	uv run src/main.py \
		--origin "$(from)" \
		--destination "$(to)" \
		$(if $(date),--date $(date)) \
		$(if $(return_date),--return_date $(return_date)) \
		$(if $(currency),--currency $(currency)) \
		$(if $(seat),--seat $(seat)) \
		$(if $(provider),--provider $(provider)) \
		$(if $(limit),--limit $(limit)) \
		$(if $(max_stops),--max_stops $(max_stops)) \
		$(if $(max_price),--max_price $(max_price)) \
		$(if $(csv),--csv) \
		$(if $(json),--json) \
		$(if $(force_refresh),--force_refresh) \
		$(if $(verbose),--verbose)

# Run code linting and formatting checks
lint:
	uv run ruff check .
	uv run ruff format --check .

# Automatically fix linting issues and format code
format:
	uv run ruff check --fix .
	uv run ruff format .

# Run test suite
test:
	uv run pytest

# Comprehensive check: format, lint, and test
check: format lint test

# Remove cached flight queries older than 3 days
clean-cache:
	@COUNT=$$(find .cache/flights -name "*.json" -type f -mtime +3 | wc -l); \
	find .cache/flights -name "*.json" -type f -mtime +3 -delete; \
	echo "Cleaned up $$COUNT old flight cache files."

# Clean environment
clean:
	rm -rf .venv .cache
