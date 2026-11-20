# Code Standards

- **Indentation**: Use **Tabs** exclusively for all code.
- **Exception**: Use **Spaces (2 or 4)** only for YAML if required by the specification.
- **Formatting**: Always run `make format` and `make lint` before finishing any task to ensure compliance with the project's Ruff configuration.

# Environment & Execution

- **CLI Tool**: The primary way to run searches and benchmark listings is the `airbnb` CLI executable, installed in PATH (`~/.local/bin/airbnb`). Run `airbnb --help` for options.
- **CLI Reinstall Mandate**: The installed CLI is a snapshot of this repo, not a live link. After committing any change under `airbnb/src/`, run `uv tool install --force ~/repos/agent-tools/airbnb` so agents using `airbnb` execute the updated code; verify with `airbnb --help` or a single `--room` run before reporting results.
- **Make Targets**: Use `make` commands strictly for development lifecycle tasks: `make format`, `make lint`, and `make test`. Do not create or use a `make run` target.

# Testing & Validation

- **Test Suite**: Use `make test` to validate changes.

# Currency & Domain Standards

- **Primary Currency**: **ALWAYS** evaluate, search, and report Airbnb prices in **CAD** unless the user explicitly requests otherwise.
- **Listing URLs**: **ALWAYS** format Airbnb listing URLs using the Canadian domain: `https://www.airbnb.ca/rooms/<id>`. When dates are known or evaluated, **ALWAYS** attach `?check_in=YYYY-MM-DD&check_out=YYYY-MM-DD&adults=1` directly to the URL. Never use `airbnb.com`.
- **Nightly Rate Requirement**: **ALWAYS** explicitly output and report the nightly rate (e.g. CAD $XX.XX/night or /nt) alongside total prices in CLI outputs and agent summaries, whether presenting a single listing or multiple listings.
- **Visitor Policy**: **ALWAYS** flag listings whose house rules explicitly ban visitors (e.g. "no visitors", "only registered guests may enter") — the user wants to bring an occasional date over.

# Development Workflow Mandates

After every major code change, the following steps MUST be performed in order:
1. **Format:** Run `make format` to ensure code style compliance.
2. **Test:** Run `make test` to ensure no regressions were introduced.
3. **Stage:** Stage all relevant changes.
4. **Commit:** Provide a detailed commit message and execute the commit.

Do not propose or perform a commit until formatting and testing have passed successfully.
