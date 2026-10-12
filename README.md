# bafin-wid-reporter

Daily monitor for the BSI CERT-Bund WID security advisory feed. Each run:

1. Reads the RSS feed and takes every advisory published in the lookback window (default 24h).
   New/updated status comes from the `[NEU]` / `[UPDATE]` title prefix.
2. Fetches full details per WID (UUID lookup + content endpoint).
3. Skips WIDs already stored with the same `latestrevision` and `currentreleasedate` (already reported).
4. Tags hits from `config/matchlists.yaml` and filters on `risk_levels`
   (match hits are kept regardless of risk when `match_overrides_risk_filter: true`).
5. Stores every fetched WID in DuckDB (`data/wids.duckdb`) and writes `output/report-YYYY-MM-DD-HHMMSS.html` (local time).
6. Optionally posts a full-width Adaptive Card to a Teams Workflows webhook
   (with `send_mode: matches_only`, nothing is posted when there are no match hits).

If the RSS feed cannot be loaded, the run writes `report-...-failed.html` with the error,
posts a failure card to Teams (if enabled), and exits with code 1. Rerun with
`--lookback HOURS` covering the missed period.

## Setup

```sh
uv sync
cp .env.example .env   # only needed when teams.enabled is true
```

## Usage

```sh
uv run run.py                      # normal daily run
uv run run.py --dry-run            # no DB writes, no Teams; report-YYYY-MM-DD-HHMMSS-dryrun.html
uv run run.py --lookback 48        # override the window in hours
uv run run.py --cleanup            # remove WIDs not seen for retention.db_days (or --older-than DAYS)
uv run run.py --cleanup-reports    # delete reports older than retention.report_days
uv run run.py --no-teams --verbose
uv run run.py --config-dir /path/to/config
```

Relative paths in `config.yaml` are resolved against the parent of the config folder.

## Scheduling

Runs once and exits. Example crontab entry for 15:00 Europe/Amsterdam:

```cron
CRON_TZ=Europe/Amsterdam
0 15 * * * cd /path/to/bafin_wid_reporter && uv run run.py >> run.log 2>&1
```

## Tests

```sh
uv run pytest
```
