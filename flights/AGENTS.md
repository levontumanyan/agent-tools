# Code Standards

- **Indentation**: Use **Tabs** exclusively for all code.
- **Exception**: Use **Spaces (2 or 4)** only for YAML if required by the specification.
- **Formatting**: Always run `make format` and `make lint` before finishing any task to ensure compliance with the project's Ruff configuration.

# Environment & Execution

- **Command Policy**: **ALWAYS** use `make` commands for all operations (running, testing, linting).
- **Prohibited**: Do **NOT** run or suggest direct `uv` or `python3` command calls.

# Testing & Validation

- **Test Suite**: Use `make test` to validate changes.
- **Comprehensive Verification**: Use `make check` to run format, lint, and tests.

# Currency & Search Standards

- **Primary Currency**: **ALWAYS** evaluate, search, and report flight prices in **CAD** unless the user explicitly requests otherwise.
- **Providers**: Pluggable provider architecture under `src/providers/`.
