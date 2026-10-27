# Code Standards

- **Indentation**: Use **Tabs** exclusively for all code.
- **Exception**: Use **Spaces (2 or 4)** only for YAML if required by the specification.
- **Formatting**: Always run `make format` and `make lint` before finishing any task to ensure compliance with the project's Ruff configuration.

# Environment & Execution

- **CLI Tool**: The primary way to run searches and benchmark listings is the `airbnb` CLI executable, installed in PATH (`~/.local/bin/airbnb`). Run `airbnb --help` for options.
- **Make Targets**: Use `make` commands strictly for development lifecycle tasks: `make format`, `make lint`, and `make test`. Do not create or use a `make run` target.

# Testing & Validation

- **Test Suite**: Use `make test` to validate changes.

# Currency & Domain Standards

- **Primary Currency**: **ALWAYS** evaluate, search, and report Airbnb prices in **CAD** unless the user explicitly requests otherwise.
- **Listing URLs**: **ALWAYS** format Airbnb listing URLs using the Canadian domain: `https://www.airbnb.ca/rooms/<id>`. Never use `airbnb.com`.
- **Nightly Rate Requirement**: **ALWAYS** explicitly output and report the nightly rate (e.g. CAD $XX.XX/night or /nt) alongside total prices in CLI outputs and agent summaries, whether presenting a single listing or multiple listings.

# Development Workflow Mandates

After every major code change, the following steps MUST be performed in order:
1. **Format:** Run `make format` to ensure code style compliance.
2. **Test:** Run `make test` to ensure no regressions were introduced.
3. **Stage:** Stage all relevant changes.
4. **Commit:** Provide a detailed commit message and execute the commit.

Do not propose or perform a commit until formatting and testing have passed successfully.
