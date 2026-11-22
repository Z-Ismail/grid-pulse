# Grid Pulse: notes for Claude Code

GB electricity data platform. Loads half-hourly carbon intensity from the NESO Carbon Intensity
API into ClickHouse, keeps every forecast/actual version, and models it with dbt into a daily mart
that tracks national forecast accuracy. Portfolio project; README.md has the design decisions and
findings. Read it before changing the loader or the models.

## Rules

- Secrets only in `.env` (git-ignored). The ClickHouse credentials in `docker-compose.yml` are local-only.
- Timestamps are timezone-aware UTC everywhere. Reject naive datetimes. The 25 Oct 2026 clock-change
  bug came from naive parsing, and a regression test guards it: keep it passing.
- Windows are half-open `[start, end)` on slot start. Loader `--end` is exclusive.
- Never change a README finding or number without re-running the analysis that produced it.
- Roadmap items (IRIS streaming, Airflow, Terraform, SLAs) are not built yet. `airflow/`, `infra/`
  and `ingest/stream/` are placeholders. Don't describe them as working.

## Run it

```bash
cp .env.example .env            # first time only
docker compose up -d            # ClickHouse on 8123 (HTTP) and 9000 (native)
uv venv --python 3.12 .venv && uv pip install -r requirements.txt   # or python3.12 -m venv + pip
docker exec -i grid-pulse-clickhouse clickhouse-client --user grid --password grid \
  --multiquery < clickhouse/schema/001_carbon_intensity.sql
.venv/bin/python -m ingest.batch.load_carbon_intensity --start 2026-11-01 --end 2026-11-03
.venv/bin/dbt build --project-dir dbt --profiles-dir dbt
```

## Test it

```bash
.venv/bin/ruff check .            # if ruff isn't in the venv: uv tool run ruff check .
.venv/bin/python -m pytest -v     # unit tests: no network, no database
.venv/bin/dbt build --project-dir dbt --profiles-dir dbt   # needs ClickHouse running
```

CI (`.github/workflows/ci.yml`) runs the same three: ruff, pytest, then a small load and dbt build
against a ClickHouse service.

## Layout

- `ingest/batch/carbon_intensity.py`: fetcher (retries with backoff and jitter, UTC parsing, window filter)
- `ingest/batch/load_carbon_intensity.py`: chunked loader into `raw_carbon_intensity`
- `clickhouse/schema/`: raw append-only table, materialised view, `carbon_intensity_latest`
  (ReplacingMergeTree)
- `dbt/models/staging/stg_carbon_intensity.sql`: `argMax` dedup (not `FINAL`)
- `dbt/models/marts/fct_carbon_intensity_daily.sql`: incremental `delete+insert` on `day`, 3-day lookback
- `dbt/macros/test_no_missing_half_hours.sql`: completeness test (48 slots per UTC day)
- `tests/`: unit tests incl. the DST regression and retry behaviour

## Working in Conductor

- Every task runs in its own Conductor workspace: a git worktree on its own branch. Work only
  inside it. Don't touch other workspaces or the original clone in `~/code`.
- `.env` files are copied into each workspace. Never print, paste or commit them.
- `.context/` is Conductor's git-ignored scratch folder. Put plans and notes for the task there.
- For anything bigger than a small fix, write a short plan first and wait for Zak's go-ahead.
- Definition of done: `ruff check .` and `python -m pytest -v` pass, and `dbt build` passes for any change to
  the loader, schema or models.
  Report the commands you ran and what they returned. Never say a check passed without running it.
- Ports: ClickHouse uses fixed ports and a fixed container name (`grid-pulse-clickhouse`), so only
  one workspace runs Docker at a time.
- Commit in small, tested steps, authored as Zak Ismail, with no co-author or attribution lines.
- When you finish a task, update the Roadmap in README.md (and any status in this file) in the same PR: tick off what is done, add any follow-ups
  you found, keep it in priority order. This list is how Zak decides what to do next.

## Shipping (fully automatic, Zak's choice)

When the task is done and the Check command passes, ship it without waiting for Zak:

1. Push the branch: `git push -u origin HEAD`. Never push to `main` directly. Never force-push.
2. Open a PR against `main` with `gh pr create --base main`: conventional-commit title, and a
   plain-English body with what changed, why, how it was tested (commands and results) and anything
   left or risky. No attribution lines, no secrets, nothing from `docs/private/`.
3. Wait for CI by polling, not `--watch`: run `gh pr checks` (no pipe to `tail`) every 30 seconds, for at
   most 15 minutes. If a check fails, fix it, push, and wait again. If a check still shows in progress
   5 minutes after its steps have finished, re-run that job once (`gh run rerun <run-id> --job <job-id>`).
   Merge only when every check is green; still pending after 15 minutes, stop and report.
4. If `gh pr view --json state` already says MERGED, skip the merge and just report it. Otherwise merge
   with `gh pr merge --squash`, then delete the remote branch: `git push origin --delete <branch>`.
5. Report the PR link, what merged and which checks passed. Zak archives the workspace.

Stop and ask Zak instead of shipping when the change: deletes data or files outside the task, changes ClickHouse table DDL or requires truncating or reloading data,
adds a paid service or a new production dependency, or Review finds anything Critical. If Check or CI
still fails after two fix attempts, stop and report rather than merging.
