# Alpha Harness v2

A local, self-improving alpha factory for [WorldQuant BRAIN](https://platform.worldquantbrain.com),
built on [Alpha Harness](https://github.com/residual-lab/alpha-harness) (MIT, © MiracleInvoker).
It runs entirely on your machine.

v2 adds, stage by stage (see the project plan):

- **Crowding history** — daily snapshots of alpha and user counts per dataset and field, so the
  search can avoid datasets that are filling up (prod correlation). *(done)*
- Alpha-type separation (regular, RA, Power Pool, current theme, SuperAlpha), submittable views
- Models trained on your alphas that predict every check and correlation before simulating
- A repair engine for near-misses and every failing check
- Live learning from every simulation, check and submission

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
