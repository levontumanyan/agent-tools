# Flight Benchmarker

A CLI tool to search, score, and rank flight options based on custom utility benchmarks and stackable penalty multipliers.

# Features

- **Multi-Provider Architecture**: Pluggable provider system starting with Google Flights (via `fast-flights`), with Amadeus and Kiwi planned.
- **Two-Phase Scoring Engine**:
  - **Base Scores**: Weighted metrics for price efficiency, total duration, departure convenience, and airline quality.
  - **Stackable Penalties**: Multipliers that punish tight connections (<75m), grueling layovers (>4h), overnight transfers, and excessive stops without outright disqualifying the option.
  - **Hard Filters**: Strict thresholds for maximum stops, price limits, and minimum layover duration.
- **Local Disk Caching**: Fast JSON caching with configurable TTL to minimize network requests.
- **Terminal & File Reporting**: Clean ASCII terminal tables plus exportable CSV and JSON reports.

# Quick Start

```bash
# Default search (Montreal YUL to Paris CDG, CAD currency)
make run

# Custom route and date
make run from=YUL to=CDG date=2026-10-25

# Round-trip flight with filters
make run from=JFK to=LAX date=2026-10-20 return_date=2026-10-27 max_stops=1

# Export to CSV and JSON reports
make run from=YUL to=LHR date=2026-11-01 csv=true json=true
```

# Scoring Methodology

## Base Score

Each flight itinerary receives a base score from 0 to 100 based on weighted metrics configured in `benchmarks.json`:

+-----------------------+--------+----------------------------------------+
| Metric                | Weight | Evaluation Logic                       |
+-----------------------+--------+----------------------------------------+
| Price Efficiency      | 35%    | Compared against cheapest in search    |
| Duration Efficiency   | 25%    | Compared against shortest in search    |
| Departure Convenience | 20%    | Boosts daytime departures (08:00-19:00)|
| Airline Quality       | 20%    | Preferred tier vs budget carriers      |
+-----------------------+--------+----------------------------------------+

## Stackable Penalties

Penalties apply multiplicative deductions to the base score:

+-------------------------+------------+------------------------------------+
| Penalty                 | Multiplier | Trigger Condition                  |
+-------------------------+------------+------------------------------------+
| Tight Layover (<75m)    | 0.60x      | Connection time under 75 minutes   |
| Grueling Layover (>4h)  | 0.70x      | Single layover exceeding 4 hours   |
| Overnight Layover       | 0.50x      | Overnight stay between legs        |
| Multiple Stops (2+)     | 0.65x      | 2 or more stops                    |
+-------------------------+------------+------------------------------------+

# Makefile Commands

- `make run` — Run flight search with CLI parameters.
- `make format` — Format all code using Ruff (tab-indented).
- `make lint` — Run Ruff linting and style checks.
- `make test` — Execute pytest test suite.
- `make check` — Run format, lint, and test suite in sequence.
- `make clean-cache` — Prune cached flight queries older than 3 days.
