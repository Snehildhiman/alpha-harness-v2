# Alpha Harness v2

A local, self-improving alpha factory for [WorldQuant BRAIN](https://platform.worldquantbrain.com),
built on [Alpha Harness](https://github.com/residual-lab/alpha-harness) (MIT, © MiracleInvoker).
It runs entirely on your machine.

v2 adds (see **[GUIDE.md](GUIDE.md)** for how to use each):

- **Alpha Types**: regular, region-agnostic, Power Pool, current-theme and SuperAlpha tabs, each
  judged only by the checks its type answers to (prod correlation for regular and RA, Power Pool
  correlation for Power Pool), with stale correlation passes flagged for a re-check.
- **Prod floor**: a local lower bound on prod correlation from alphas BRAIN already scored.
- **Learned models** that predict every check and correlation before you simulate, retrain
  themselves as results arrive, and screen the labs' candidates.
- **Repair**: model-ranked variants of near-miss alphas, RA families included.
- **Transplants**: passing alphas tried in the regions they have not run in, ranked by the models.
- **Autopilot** (off by default): queues the best transplants on a daily budget while you are away.
- **RA promotion**: expressions passing in 2+ markets run once as region-agnostic families.
- **Scorecards**: which operators, fields, datasets and lookbacks run hot or cold.
- **Dedup** of equivalent expressions and of alphas already in your vault.
- **Crowding**: daily snapshots of alpha and user counts per dataset and field, with a screen ranking the fastest growers.
- **Research**: free arXiv / RSS papers the LLM labs draw on.
- **Governor**: cores dealt toward the tasks whose alphas pass.
- **Competitions**: your rank kept over time, with a trend line.
- **Today's openings** on the dashboard: submittable and re-check counts per type.

## Requirements (Windows 11)

Check each in PowerShell; install what is missing, then reopen PowerShell.

| Tool | Check | Need | Install |
| --- | --- | --- | --- |
| Git | `git --version` | any | `winget install --id Git.Git -e` |
| uv | `uv --version` | 0.12+ | see below |
| Python | `uv python list --only-installed` | 3.14 | `uv python install 3.14` |
| Node.js | `node --version` | 22.12+ | `winget install OpenJS.NodeJS.LTS` |
| pnpm | `pnpm --version` | 12.6.0 | `npm install -g pnpm@12.6.0` |

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Setup

```powershell
git clone https://github.com/Snehildhiman/alpha-harness-v2.git
cd alpha-harness-v2
cd backend;  uv sync
cd ..\frontend;  pnpm install
```

## Run

Two terminals:

```powershell
# Terminal 1
cd backend;  uv run uvicorn alpha_harness.main:app --port 8000
```

```powershell
# Terminal 2
cd frontend;  pnpm dev
```

Open http://localhost:5173 and sign in with your BRAIN account.

For long runs: keep the laptop plugged in, power mode **Best performance**, and closing the lid
set to **Do nothing** when plugged in.

## Daily catalog sync

With the app running and signed in, the data catalog downloads once a day from 06:00 local
time, and the region-agnostic market every 3 days. Each sync leaves a dated crowding snapshot.
The settings live in `Preferences` (`daily_sync`, `daily_sync_hour`, `ra_sync_days`).

API: `GET /api/crowding/days`, `GET /api/crowding/datasets?region=USA&delay=1&universe=TOP3000&days=7`,
`GET /api/crowding/fields?...&datasetId=...`.

## Tests

```powershell
cd backend;  uv run pytest
```

## Local data

Your login, simulations and synced data are stored in `~/.alpha-harness/` (set `AH_DATA_DIR` in a
`.env` file in the repository root to use another folder). Nothing there is committed.
