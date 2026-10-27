# NBA Handicapping

Python 3.12+ project scaffold for an NBA handicapping application using the Tank01 RapidAPI feed.

Install with `pip install -e ".[test]"`. Copy `.env.example` to `.env` and supply your RapidAPI key before adding feed integration.

```text
src/nba_handicap/
  api/       Tank01 client, odds fetching, and rate-limit handling
  models/    Tank01 odds, game, and team schemas
  analysis/  Handicapping, props, and value calculations
  storage/   Local caching and SQLite odds snapshots
  cli.py     Command-line entrypoint
tests/       Unit tests
```

The integration and analysis modules are placeholders.
