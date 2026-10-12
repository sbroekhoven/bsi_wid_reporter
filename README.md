# bsi-wid-reporter

> **Note:** I built this project as an example project for a Python training I took.

Monitor for the BSI CERT-Bund WID security advisory feed. It runs in one of three modes:

| Mode | What it does |
| --- | --- |
| *(no flag)* | Sync, then report the WIDs not reported before (steps 1 to 6 below). |
| `--sync` | Steps 1, 2 and 5 only: fetch the window from the feed and store it. No report, no Teams post. |
| `--report` | Report from the database only, without fetching the feed (see [Sync and report separately](#sync-and-report-separately)). |

A run without a flag:

1. Reads the RSS feed and takes every advisory published in the lookback window (default 24h).
   New/updated status comes from the `[NEU]` / `[UPDATE]` title prefix.
2. Fetches full details per WID (UUID lookup + content endpoint).
3. Skips WIDs already stored with the same `latestrevision` and `currentreleasedate` (already reported).
4. Tags hits from `config/matchlists.yaml` and filters on `risk_levels`
   (match hits are kept regardless of risk when `match_overrides_risk_filter: true`).
5. Stores every fetched WID in DuckDB (`data/wids.duckdb`) and writes `output/report-YYYY-MM-DD-HHMMSS.html` (local time).
6. Optionally posts a full-width Adaptive Card to a Teams Workflows webhook
   (with `send_mode: matches_only`, nothing is posted when there are no match hits).

If the RSS feed cannot be loaded, the run (also with `--sync`) writes `report-...-failed.html` with the
error, posts a failure card to Teams (if enabled), and exits with code 1. Rerun with
`--lookback HOURS` covering the missed period.

## Sync and report separately

Run `--sync` often (e.g. hourly) and `--report` when you need a report.

- `--report` lists every WID that was first stored, or stored with a new revision, within the
  lookback window (`last_changed_at` in the database). It does not track what was reported before,
  so two reports with overlapping windows show the same WIDs.
- Match lists and `risk_levels` are applied when the report is built, so changes to
  `matchlists.yaml` or `config.yaml` also apply to WIDs synced earlier. For example, after adding
  `MITTEL` to `risk_levels`, `--report --lookback 168` reports the past week with the new filter.
- `--report` posts to Teams (if enabled). `--sync` posts only when the feed cannot be loaded.
- DuckDB allows one writing process at a time. A sync only holds the write lock while saving, and
  both modes retry for up to 30 seconds when the database is locked.

## Setup

```sh
uv sync
cp .env.example .env   # only needed when teams.enabled is true
```

## Usage

```sh
uv run run.py                      # normal daily run: sync + report
uv run run.py --sync --lookback 3  # store the last 3 hours in the DB, no report
uv run run.py --report             # report from the DB for the last lookback_hours
uv run run.py --report --lookback 168  # report from the DB for the last week
uv run run.py --dry-run            # no DB writes, no Teams; report-YYYY-MM-DD-HHMMSS-dryrun.html
                                   # (--sync --dry-run fetches only; --report --dry-run skips Teams)
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
0 15 * * * cd /path/to/bsi_wid_reporter && uv run run.py >> run.log 2>&1
```

Or sync hourly and report once a day. The sync window overlaps (3 hours) so a single failed
sync is caught up by the next one; the 24-hour report window matches the report schedule:

```cron
CRON_TZ=Europe/Amsterdam
5 * * * *  cd /path/to/bsi_wid_reporter && uv run run.py --sync --lookback 3 >> run.log 2>&1
0 15 * * * cd /path/to/bsi_wid_reporter && uv run run.py --report --lookback 24 >> run.log 2>&1
```

## Tests

```sh
uv run pytest
```
