# Changelog

What v2 adds on top of [alpha-harness-improved](https://github.com/residual-lab/alpha-harness)
(MIT, © MiracleInvoker). How to use each part: [GUIDE.md](GUIDE.md).

## 2026-10-21 (from your notes)

- **Models no longer guess on bad input**: *Ask before you simulate* first checks the
  expression (it must parse, use your account's operators, read fields that exist in the chosen
  market, put vector fields inside `vec_`, keep Power Pool limits) and says what is wrong.
  Region, delay, universe and neutralization are BRAIN's own dropdowns. Checks for other
  regions (GLB AMER for an ASI alpha) are hidden, and numbers from models that only guess are
  struck through.
- **Filters** on Alpha Types, Repair near-misses and transplants: region, dataset, data
  category, universe, neutralization, minimum Sharpe and fitness, maximum turnover, text search,
  theme datasets. Dataset and category choices show how many alphas use each, so a tab can be
  split by dataset. *Re-check top N* follows the filters.
- **Theme datasets**: BRAIN's theme tags (the ×1 badge) are synced with the catalog; a *Theme
  datasets* toggle in the Data Explorer and a filter on the alpha lists.
- **Improve any alpha**: every Alpha Types row links to Repair (failing) or Improve (passing:
  variants ranked by predicted Sharpe or fitness among those likely to keep passing).
- **RA without an LLM**: choose *All regions* in the Template or Search Lab, or use Repair's
  transplants and promotions. The Region Agnostic Lab says so.
- **Ten more block templates** in Basic Template Research, shaped for less crowded signals
  (volatility-scaled change, steady field, two-field spread, field-price divergence, quiet days,
  ratio momentum, rank change, peer-relative trend, …).
- **Models**: crowd growth from the daily snapshots is a new input (used by model sets trained
  from now on).
- Simulations stay at BRAIN's daily allowance (5,000); the app cannot raise it, only spend it
  better (dedup, screening, autopilot).

## 2026-10-21 (overnight)

**More submittable alphas from what you already have**

- **Transplants** (Repair): every passing regular or Power Pool alpha, tried in each downloaded
  region it has not run in, with the same settings and a universe of the same size, and only
  where that region carries every field it reads. Ranked by the models. Correlation is measured
  against each region's own crowd, so an alpha crowded in USA can be quiet in EUR or ASI.
- **Promote to region agnostic** (Repair): expressions that already pass as regular alphas in
  two or more of USA, EUR, ASI and GLB, and never ran as RA, run once as region-agnostic
  families in the RA universe you pick.
- **Autopilot** (Settings, off by default): every 30 minutes, once its last task has finished,
  queues up to 20 simulations: RA families first (when an RA universe is chosen), else the best
  transplants (chance of passing ≥ 40%), up to 100 simulations a day.
- **Universe variants** in Repair, aimed at robust-universe and sub-universe failures (e.g. ASI).

**Seeing it**

- **Today's openings** on the dashboard: submittable and re-check counts per alpha type, with
  near-miss and transplant counts.
- **Crowding** screen: datasets and fields ranked by how many new alphas and users they gained
  over 1, 7 or 30 days, from the daily catalog snapshots.
- **Competitions**: your rank in each ongoing competition is read every 6 hours and kept, so
  each card shows how it moved.
- **Research**: one-click free feeds (Quantpedia, Alpha Architect) beside arXiv.

**Speed**

- Alpha Types on a 50k vault: about 7 s on the first load, then about 50 ms (incremental crowd
  floors, throttled re-judging).

## 2026-10-20

- **Alpha Types**: regular, region-agnostic, Power Pool, current-theme and SuperAlpha tabs, each
  judged only by its own checks, split into submittable, needs re-check, pending, failing and
  submitted. Old correlation passes go to *Needs re-check*; *Re-check top N* costs no
  simulations.
- **Power Pool themes** checked locally, with a theme calendar.
- **Learned models** (LightGBM): prod, Power Pool and self-correlation, Sharpe, fitness,
  turnover and every check, tested on your newest alphas against a baseline. They retrain by
  themselves as results arrive, behind a gate that keeps the better set.
- **Repair**: hundreds of one-step variants of each near-miss (prod correlation 0.70–0.75,
  narrow check failures), ranked by the models; RA families scored region by region.
- **Dedup**: equivalent spellings of one expression, and alphas already in your vault, are never
  simulated twice.
- **Screening**: the Search and Template labs ask for 4× the candidates and simulate the ones the
  models rate best, keeping 20% random so the models keep learning.
- **Scorecards**: operators, operator pairs, fields, datasets, categories, lookbacks and settings
  that run hot or cold on each correlation.
- **Prod floor**: a local lower bound on prod correlation from alphas BRAIN already scored.
- **Crowding history** and a **daily catalog sync**.
- **Research**: arXiv q-fin and your own feeds, carried into the LLM Power Pool and Region
  Agnostic labs one paper a call.
- **Governor**: cores re-dealt toward the tasks whose alphas pass.
- **Ollama** as a free, unlimited local LLM provider.
