.PHONY: survey lint format test check setup clean

cities ?=
check_in ?=
check_out ?=
currency ?=
min_rating ?=
min_reviews ?=

survey:
	uv run src/main.py --survey \
		$(if $(cities),--cities "$(cities)") \
		$(if $(check_in),--check_in $(check_in)) \
		$(if $(check_out),--check_out $(check_out)) \
		$(if $(currency),--currency $(currency)) \
		$(if $(min_rating),--min_rating $(min_rating)) \
		$(if $(min_reviews),--min_reviews $(min_reviews))

# Run code linting and formatting checks
lint:
	uv run ruff check .
	uv run ruff format --check .

# Automatically fix linting issues and format code
format:
	uv run ruff check --fix .
	uv run ruff format .

# Run tests
test:
	uv run pytest

# Comprehensive check: format, lint, and test
check: format lint test

# Setup git hooks
setup:
	cp scripts/setup_hooks.sh .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	echo "Git hooks installed successfully."

# Remove cached listings older than 7 days
clean-cache:
	@COUNT=$$(find .cache/listings -name "*.json" -type f -mtime +7 | wc -l); \
	find .cache/listings -name "*.json" -type f -mtime +7 -delete; \
	echo "Cleaned up $$COUNT old cache files."

# Remove temporary files and the virtual environment
clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
