# Alpha Harness v2 — Guide

How to run it, what each part does, how it learns, and how to change it yourself.

## 1. First run (do these once, in order)

1. **Start it** (two PowerShell windows, see `README.md`) and open http://localhost:5173.
2. **Sign in** with your BRAIN account.
3. **Sync the data catalog** — *Sync* screen → download every market. Needed for field
   categories (themes), crowding counts and the models. Region `ALL` (region-agnostic) is a
   separate, slower download on the same screen; run it too if you work on RA alphas.
   After this, the catalog re-downloads by itself every morning (Settings → daily sync).
4. **Import your alphas** — *Alphas* screen → *Sync alphas*. ~50k alphas is about 500 requests.
   Let it finish (overnight is fine).
5. **Train the models** — *Models* screen → *Train models*. A minute or two for 50k alphas. After
   that they retrain by themselves whenever 100 new or re-checked alphas arrive.
6. **Check the theme calendar** — *Alpha Types → Current Theme → Theme calendar*. Add each
   new Power Pool theme from BRAIN's calendar when it is published.

## 2. Daily use

| Goal | Where | What to do |
| --- | --- | --- |
| See what can be submitted | **Alpha Types** | Pick the tab (Regular, Region Agnostic, Power Pool, Current Theme, SuperAlpha). *Submittable* is safe now; *Needs re-check* passed but its correlation result is old. |
| Refresh old correlation results | Alpha Types → *Needs re-check* | *Re-check top N*. No simulations are spent. Alphas whose **Prod floor** is already ≥ 0.7 are skipped: they cannot pass. |
| Fix near-misses | **Repair** | Pick an alpha that fails narrowly (e.g. prod corr 0.70–0.75, robust universe in ASI). The models rank one-step variants; *Simulate top N* queues the best. RA families are repaired region by region. |
| Try alphas in other regions | **Repair → Transplants** | Every passing regular or Power Pool alpha (each keeps its type), in each downloaded region it has not run in (same settings, same-size universe, only where every field exists). Ranked by the models; *Simulate top N*. Passing in 2+ regions makes an all-region alpha. |
| Turn all-region alphas into RA | **Repair → Promote to region agnostic** | Expressions that already pass as regular alphas in 2+ of USA/EUR/ASI/GLB and never ran as RA. Pick the RA universe (needs region ALL downloaded) and *Run top N as RA*. |
| Find new alphas | **Research Labs** | Search / Template / Evolution / LLM labs. Search and Template rounds are **screened** by the models (Settings → Model screening). |
| Use papers | **Research** | Tick papers, then add an LLM Power Pool or Region Agnostic Lab task: each LLM call carries one paper's idea over to your fields. |
| Learn what to avoid | **Scorecards** | Which operators, pairs, fields, datasets, categories, lookbacks and settings run hot or cold on prod / Power Pool / self-correlation. |
| Check the models | **Models** | Accuracy on your newest alphas, what drives each prediction, *Screening in the labs* (model picks vs random picks), and a box to predict any expression before simulating. |
| Track competitions | **Competitions** | Your rank in each ongoing competition is read every 6 hours and kept, so each card shows how it moved. Only your own standing is read. |
| Spend cores well | **Tasks** | *Yield* column per task; *Re-deal cores by yield* (or turn it on in Settings to run every 30 min). |

## 3. How it decides

**Alpha types and their checks** (`backend/src/alpha_harness/separation.py`)

| Type | Must pass |
| --- | --- |
| Regular | standard checks, self-correlation, prod correlation (< 0.7, or BRAIN's PASS) |
| Region agnostic | the regular rules in at least 2 regions |
| Power Pool | standard checks, self-correlation, Power Pool correlation (prod does not apply) |
| Current theme | Power Pool rules + the running theme's rule (delay, data categories, single category), checked locally (`themes.py`) |
| SuperAlpha | its own checks, self- and prod correlation |

A passing correlation result older than *Trust a correlation pass for* (default 1 day) moves to
*Needs re-check*: correlations only rise as others submit.

**Prod floor** (`crowding/crowdmap.py`). If a landmark alpha has prod correlation `p` and a new
alpha correlates `r` with it, the new alpha's prod correlation is at least
`r·p − √((1−r²)(1−p²))`. Landmarks are your alphas BRAIN scored at ≥ 0.6, and every submitted
alpha (p = 1). Needs the daily PnL of both, which the alpha import downloads for alphas that
pass their checks.

**Dedup** (`canon.py`, `engine/vault_dedup.py`). Expressions are rewritten into one spelling
(`add(a,b)` = `b + a`, `rank(rank(x))` = `rank(x)`, `20.0` = `20`, variable names…) and matched
against everything already simulated *and* every alpha in your vault, so nothing is paid for
twice.

**Screening** (`labs/screen.py`). A Search/Template round asks the sampler for 4× the points it
sends, the models score each by its chance of passing everything its type needs, the best are
simulated and 20% are picked at random to keep learning.

## 4. How it learns

* **Models** (`models/`): LightGBM, one per target — prod / Power Pool / self-correlation
  *values*, Sharpe, fitness, turnover, and pass/fail for every check with enough examples.
  Inputs: settings, expression structure (operators, parent→child operator pairs, lookbacks,
  size), datasets and categories of the fields, field crowding (alpha and user counts), and date.
* **Honest testing**: the newest 20% of alphas are held out; every score sits beside a
  know-nothing baseline.
* **Live learning**: every 10 minutes the app looks for new or re-checked alphas; at 100 it
  retrains. A new set replaces the old one only if it scores at least as well on alphas the old
  set never saw (the *gate*). Turn off with Settings → *Retrain the models by themselves*.
* **Scorecards** and **crowding history** update from the same data, so every simulation,
  re-check and submission feeds all of them.

## 5. Settings worth knowing

| Setting | Default | Effect |
| --- | --- | --- |
| Model screening | 4× | Candidates asked per candidate simulated. Off = simulate every point. |
| Exploration share | 20% | Part of each screened round picked at random. |
| Trust a correlation pass for | 1 day | Older passes need a re-check. |
| Re-deal cores by yield | off | Moves cores toward tasks whose alphas pass. |
| Autopilot | off | Every 30 min queues up to 20 of the best transplants (chance ≥ 40%), once its last task has finished, up to 100 simulations a day. *Run one round now* on Repair → Transplants. |
| Daily sync / hour / RA every | on / 06:00 / 3 days | Catalog downloads that build the crowding history. |
| Read research feeds | on | arXiv q-fin + your own Atom/RSS feeds, twice a day. |
| Auto update | off | Installs releases from this repo only when you turn it on. |

LLMs are optional. Free routes: **Google AI Studio** key (free tier), **Ollama** on this
computer (no key, unlimited, slower), and the other free providers on *LLM Integration*.

## 6. Changing it yourself

| You want to… | Edit |
| --- | --- |
| change a type's rules | `backend/src/alpha_harness/separation.py` (tests: `backend/tests/test_separation.py`) |
| change near-miss margins or repair edits | `repair/rank.py`, `repair/generate.py` |
| add a model input | `models/features.py` (`matrix`, `fit_vocabulary`) |
| change how candidates are ranked | `repair/rank.py::score`, `labs/screen.py::chance_of` |
| add a canonical rewrite | `canon.py` — only rewrites that cannot change BRAIN's result |
| add a feed | Settings, or `research/feeds.py` for a new format |
| add a screen | `frontend/src/screens/<name>/`, then `frontend/src/router.tsx` and `frontend/src/shell/nav.ts` |

After changing backend API models, regenerate the frontend types:

```powershell
sh frontend/tools/codegen/generate.sh frontend/src/api/generated.ts
```

Before pushing, run what CI runs:

```powershell
cd backend; uv run ruff check .; uv run ruff format --check .; uv run basedpyright; uv run pytest
cd ..\frontend; pnpm check; pnpm build
```

## 7. Troubleshooting

* **Current Theme shows 0**: sync the data catalog (categories come from it) and check the
  calendar has today's theme.
* **Prod floor is empty**: the PnL of your alphas has not been downloaded yet (Alphas → sync),
  or no alpha in that region has a stored prod correlation of 0.6 or more.
* **Models screen says too few labels**: a target needs 300 labelled alphas; re-checks add
  correlation labels fastest.
* **Research says a feed could not be read**: check the address in Settings; arXiv is free and
  needs no account.
* **CI failed email**: open the run on GitHub; the failing step names the check.
