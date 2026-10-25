# Changelog

What v2 adds on top of [alpha-harness-improved](https://github.com/residual-lab/alpha-harness)
(MIT, © MiracleInvoker). How to use each part: [GUIDE.md](GUIDE.md).

## 2026-10-25 (theme sub-region Sharpe misses are failures)

- **LOW_GLB_AMER_SHARPE below 1 reads FAIL while the Nov`26 theme runs**: BRAIN reports the
  miss as a WARNING, but the theme needs AMER Sharpe above 1. Check lists show FAIL for the
  sub-regions a running Power Pool theme names in its *Sub-region Sharpe above* field (AMER
  for Nov`26), and the Current Theme tab and the lab's combo score already count it against
  the Alpha. Other sub-regions, other regions, and regular Alphas keep BRAIN's own reading,
  and once the theme ends the badge goes back to WARNING.

## 2026-10-25 (Current Theme Lab: Full checks and templates)

- **Full or Quick, per task**: the lab used whatever Settings chose for the region, and
  Settings had Quick mode on, so its Alphas ran Quick. A new *Check* choice: **Full** (the
  default: a normal simulation with BRAIN's whole check list), **Quick** (fewer checks, faster;
  a passing Alpha is re-run in Full) or **As in Settings**.
- **Choose the templates to simulate**: twelve one-field templates (rank, own history, z-score
  over time, smoothed level, decayed rank, change, smoothed change, industry relative and its
  history, industry-neutral change, country then sector, stability), each with what it does,
  *suggested* and *low turnover* badges and its pass rate so far. Pick several (*Suggested*,
  *Low turnover only*, *All*, *Clear*) and keep or turn off the lab's own shapes beside them.
  Templates an account lacks an operator for, or that read a group field the theme forbids,
  are shown but cannot be ticked. On GLB each is still standardised within its country. The
  template leaderboard names them.
- **20 more templates (32 in all)**: winsorized z-score, history, change and smoothed level;
  scale, scale over time and its smoothed form; normalize; quantile and rolling quantile;
  signed square root; sector scaled; sub-industry winsorized z-score; distance from average;
  days since the high, the low and the last update; size of the last change; hump-smoothed
  rank and exponential decay (both low turnover). Each stays inside Power Pool's eight
  operators with the GLB country step; ones your account lacks an operator for cannot be
  ticked.
- **Templates show at once**: the list waited on reading your operators (which could go to
  BRAIN) and on counting every past trial for pass rates, and showed nothing meanwhile or on
  a failure. It now reads the stored operator list only, counts pass rates in the background
  (filled in when ready), and says when it is loading or why it failed, with *Try again*.

## 2026-10-25 (GLB/D1 Power Pool Nov`26 theme)

- **The new theme is in the calendar**: GLB, Delay 1, AMER Sharpe > 1, 26 Oct to 22 Nov, 1x,
  with BRAIN's 33 recommended datasets. A calendar saved earlier receives it by itself (and a
  theme you remove stays removed). The calendar editor gained *Sub-region Sharpe above* and
  *Recommended datasets*; the AMER floor is read from BRAIN's own GLB_AMER_SHARPE check.
- **Current Theme Lab looks a week ahead**: a theme opening within seven days can be chosen,
  so Alphas for Nov`26 can be simulated before it opens. It starts from the recommended
  datasets (*Recommended only*, *All*, *Clear*).
- **Scored for the combination**: a theme with a sub-region floor is searched on a new *Theme
  combo score*: the train-years Sharpe (held-out years untouched, for the OS Score), half of
  it after a 5 bps trading cost on its turnover (for the AC figures), less any shortfall
  below AMER Sharpe 1.
- **What to submit next for this theme**: ranks your submittable theme Alphas by what each
  adds to the combination of your theme Alphas: BC Combo IR, AC Combo IR, and both over the
  last two years (the OS proxy). Picks come in order, each judged against what you submitted
  in the theme's dates and the picks above it, so two Alphas that trade alike are not both
  picked. Missing daily PnL is downloaded in the background; no quota is spent.
- **BRAIN's GLB notes applied** (sub-geography cutoff, regional imbalance, less crowded
  datasets): on GLB every Alpha the lab writes is ranked or z-scored within its country (the
  search tries both), and country joins the group choices; fields under 70% coverage are left
  out, since a thin field leans the Alpha toward the region that has it; the combo score
  charges AMER, APAC or EMEA at 1 or below (GLB's own cutoff) and a quarter of the spread
  between the best and worst sub-region; tech_chart_model, predictive_starmine, model135 and
  analyst_consensus are offered as *less crowded* and start selected. The ranking table shows
  all three sub-region Sharpes.
- **Ranked like the Power Pool leaderboard** (Tagged Power Pool Alphas, Merged PNL, BC Combo
  IR, AC Combo IR): the summary reads your theme Alphas that way, each candidate shows the
  Merged PnL it adds, and picks weigh BC and AC Combo IR most (35% each), with the last two
  years before and after cost as a 15% + 15% check.

## 2026-10-24 (Tasks page speed)

- **Region Agnostic results load in about a second, not ten or more**: the Alpha groups were
  rebuilt from every trial and every Alpha the task ever wrote, on every four-second update,
  and sent whole (9 MB for 12,000 groups). Now only the columns shown are read, the best 300
  groups are sent ("Best 300 of 12,000"), one ranking is shared by every update for a few
  seconds, and the last one is shown at once while a fresh one is built behind it.
- **Looking up many Alphas or fields at once is about 50 times faster** everywhere (vault,
  submittable list, models, governor, task details, labs): DuckDB took 2.8 s just to accept
  36,000 ids as separate parameters; they now go as one.
- **The task list counts each running task in one pass** instead of five, every two seconds.
- **One old task with settings the app no longer accepts no longer breaks the Tasks list**
  (or stops waiting tasks from starting): a task's cores are read without re-checking all
  its settings, which was also slow for tasks searching thousands of fields.

## 2026-10-24 (sign-in identity check)

- **Fixed "Cannot reach Alpha Harness: it is not running" while verifying identity**: one
  dropped connection during the wait for BRAIN's check ended the wait. It now keeps asking
  through brief drops (saying "still trying") and gives up only after about a minute, asks one
  at a time, and no longer restarts the wait on every redraw. The app also keeps idle
  connections for 75 s instead of 5 s, so the browser no longer sends a sign-in request down a
  connection the app has just closed.

## 2026-10-23 (fixes from the refusals list)

- **Fixed "Incompatible unit … Unit[Group:1]"**: fields that are labels (a cluster, sector or
  country code; some are listed as MATRIX) were used as numbers. Every lab now leaves them out
  of its fields, the region-agnostic and Power Pool labs offer a dataset's own labels as groups
  (group_rank(…, its cluster): a rarely written idea), and an alpha that uses a label anywhere
  but as a group is refused before it is sent, saying why.
- **A simulation BRAIN failed twice for half an hour** (often a SuperAlpha combo it cannot run)
  is not sent a third time.
- The refusals list explains both.

## 2026-10-23 (speed)

- **Simulations: no idle gaps between batches.** A finished simulation now wakes the engine (a
  slot is free) and the labs (a result to plan from) at once; queued work wakes the engine.
  Before, a freed slot could wait up to about 10 seconds for three timers in a row.
- **Faster screens**: *Submittable* answers a repeat visit at once while the vault is
  unchanged (4 s before); a first read from BRAIN (quarter, pyramids) waits at most 8 seconds,
  then the screen retries while the read finishes in the background.
- **Fixed**: live updates refused when the app ran on a port other than 8000; every screen
  checked in a browser opens without an error.

## 2026-10-23 (choose templates)

- **Templates in the Region Agnostic Lab**: with the built-in writer, every template is listed
  with its name, idea and expression, marked *2+ regions* (unit-free, history- or ratio-based:
  suggested for passing in two regions) and *Low crowd* (rarely written, for prod correlation
  under 0.7), with its pass rate once it has results. Tick any number; *Suggested for 2+
  regions*, *Low crowd only* and *Clear* set the ticks; none ticked uses them all.
- **Datasets**: each shows how many of USA, EUR, ASI and GLB have it (two is enough); the least
  crowded list holds 40.

## 2026-10-23 (low prod correlation)

- **Crowded candidates are not sent**: once the models have learned prod correlation, the
  Region Agnostic Lab predicts it for each candidate in every chosen region and leaves out
  those expected at 0.6 or more in all of them (a fifth are still sent, so the models keep
  learning); the rest go quietest first.
- **Unusual ideas, drawn twice as often**: co-movement of two datasets' fields, one field with
  another's effect regressed out, how recently a figure changed, steadiness of its changes,
  signals only on busy days, signals that flip in volatile markets, skew, the field against
  returns, extremes only, analysts' disagreement (vector spread); partners from another dataset
  first; half of all candidates neutralized within an industry or smoothed.
- **Fields in one region only are skipped** by the built-in shapes (they could never pass in two).
- **ARC panel**: every dataset in both lists is a tick box, with *Tick all* / *Untick these* per
  list, the count chosen and *Clear*. **Fixed**: alphas per field read 0 for every dataset (the
  All Regions market counts none); it is now the sum over USA, EUR, ASI and GLB, and the least
  crowded list keeps datasets known in two or more regions.

## 2026-10-23 (ARC webinar)

From the ARC webinar's Q&A:

- **Currency guard**: a region-agnostic alpha that ranks an amount (sales, a price, market cap,
  volume) across stocks reporting in different currencies is not sent; the Region Agnostic
  Lab says why and how to fix it: divide by another amount, or compare with the stock's own
  history (ts_rank, ts_zscore, ts_scale). The built-in shapes never write one, and two new
  shapes divide one amount by another (favoured for fundamentals).
- **Global alphas to ARC**: Repair → Promote to region agnostic → *Global alphas* runs your
  passing and submitted Global alphas at delay 1, never run as RA, once each as an RA alpha:
  the webinar's lowest-hanging fruit.
- GLB children now face the EMEA / AMER / APAC Sharpe tests in ARC; the lab already counts
  those checks when it decides what to promote.

## 2026-10-23 (ARC)

- **Region Agnostic Lab promotes by itself**: each candidate still runs cheaply as an ordinary
  Alpha in every chosen region. When two regions pass every check but correlation (or one
  passes and another is within 7%), the same task runs it once as a real region-agnostic
  Alpha, the RA Parent ARC counts. It skips one whose passing regions all fail prod
  correlation already, since BRAIN needs one passing child under the limit. *Two pass* or
  *Never* are the other choices.
- **Judged as BRAIN judges RA children**: ASI runs with Max Trade on; the lab asks for delay 1,
  the only delay RA allows.
- **ARC datasets**: one click loads the datasets the community reports work for ARC (the
  1 October 2026 webinar and consultants' posts: pv1, fundamental17/23, other335, model38/110/
  138, analyst69, imbalance5, predictive_starmine, intraday_pv_feats, institutions6,
  analyst_factor_signals and more) that are in your All Regions catalog, or the 10 least
  crowded datasets (fewest Alphas per field).
- **Hypothesis first, away from the crowd**: the built-in shapes favour what suits each kind of
  data (analyst revisions, slow fundamentals, short reversal for price-volume and imbalance,
  smoothed model scores, step changes in holdings), take the least crowded multi-region fields
  first, and neutralize within an industry or smooth about a third of them. Four new
  hypothesis shapes (short reversal, slow level, year change, revision trend). The LLM prompt
  says the same, and that two passing regions are enough.

## 2026-10-23

- **Tasks and the other screens no longer wait for minutes while tasks run.** Each running
  Search or Template task asked its optimizer for up to 20 candidates per alpha it sent, and
  each ask grows slower with the task's trials (about 0.1 s at 3,000 trials). Several tasks
  did this at once on their own threads, which starved the thread that answers the screens.
  Now the labs plan on one shared thread, each round for at most 2 seconds (the rest on its
  next turn), the worker pool is back to its usual size, and the screens get their turn sooner.
- **Tasks list**: counts of tasks that are not running are kept, so only running tasks are
  counted on each visit (0.3 s for 250,000 trials).
- **Which templates pay**: reads only the names it needs, and answers from its last reading at
  once while a fresh one is made (every 10 minutes).
- **Responsiveness** on Health: the slowest delay of the last minute, and any stall of 2 s or
  more with where in the app it happened (also in the console as `loop.stalled`).

## 2026-10-22 (night)

- **Restore** (Health and Backup → a backup → Restore): every alpha, PnL day and crowd snapshot
  in the backup that is missing here is added back; nothing newer is replaced or deleted.
  Optionally its models, and its tasks, settings and prompts (swapped in at the next start, the
  current ones kept aside). *Add a backup file* takes a zip from another computer.
- **Automatic backup**: weekly by default (daily or off on the Health screen).
- **Why BRAIN refused simulations** (Health): refusals of the last 1, 7 or 30 days grouped by
  BRAIN's message, most common first, marked *Fix* when they would repeat, with what to do,
  an example expression and the tasks that wrote them.
- **Which templates pay** (Research Labs): every template, Search Lab shape, Region Agnostic
  shape and SuperAlpha recipe by its pass rate and mean Sharpe, once it has 5 results.
- **Submission reminder** (dashboard): alphas that passed *Check now* 2+ days ago and are still
  not submitted, with links to check again and to BRAIN.
- **Fixed**: the dashboard's transplant count leaves out transplants already simulated or
  refused; *What to submit next* and Transplants answer a repeat visit at once (kept for a
  minute while the vault is unchanged); Evolution seeds may come from any universe or region
  at the same delay when every field they read is in the breeding market, and Auto Select can
  look in the region's other universes.

## 2026-10-22 (evening)

- **Never the same failure twice**: a simulation BRAIN refused for good (an unknown field, an
  operator not allowed, bad inputs) is not sent again with the same settings; exact repeats of
  anything in the vault were already reused for free. Repair, transplants and SuperAlpha repair
  no longer offer variants that were already simulated.
- **Dead families skipped**: an expression shape (numbers aside) that failed 4+ times in a
  region and never passed there is skipped by the Search, Template, Basic Template, Current
  Theme, Evolution, Power Pool and Region Agnostic labs (Region Agnostic leaves out only that
  region).
- **Batch diversity**: a round sends at most 2 alphas of one shape; near-copies only fill a
  round that found nothing more different. The LLM and built-in writers drop near-copies in a
  batch.
- **Health and Backup** screen: BRAIN session, catalog sync, models, tasks, last day's
  simulations and errors, LLM keys, autopilot, disk and the last backup, each OK / Look / Fix
  with a link. *Back up now* zips your alphas, their PnL, the crowd history, the models and the
  app's database (saved passwords and keys stay locked); the newest 10 are kept and downloadable.
- **Since yesterday** on the dashboard (24 h or 7 days): new alphas, new submittable, new
  near-misses, simulated / errored / reused, per type, and the best new submittable.
- **Model accuracy over time** on Models: each target's held-out score at every training, with
  the change since the first; retrains that did worse are shown hollow.
- **Check now before you submit**: on *What to submit next* and every submittable or re-check
  row of Alpha Types, BRAIN's checks run again for that alpha (each region of an RA family) and
  say *Passes now · submit on BRAIN* or which check fails. No simulations spent.
- **More templates**: 18 more block templates in Basic Template Research (42 in all: trend
  efficiency, days since the high, range position, year-over-year change, acceleration, back to
  peers, volume-confirmed change, risk-scaled score, low-volatility tilt, sign persistence,
  field-volume divergence, excess over returns, co-movement break, quantile shift, held-steady
  rank, …) and 18 more families in the Template Lab gallery (30 in all).

## 2026-10-22 (afternoon)

- **SuperAlpha library**: 67 selections (55 new: correlation caps, turnover bands, broad and
  balanced books, simple expressions, by number of categories, blended scores) and 65 combos
  (55 new: IR over 20 to 750 days, floored and squared IR, inverse volatility and variance,
  mean return, crowding over other windows, uncrowded IR, momentum and positive-IR gates,
  blends). Each list has *Defaults* and *All* buttons; hovering a chip shows its expression,
  and a task over 300 SuperAlphas warns that it runs for days.

## 2026-10-22

- **No more stuck clicks**: a screen opens at once on a click (its code is loaded in the
  background after start), and a read that takes over 45 s gives up so it cannot hold the
  browser's connections. The server no longer does heavy work on its main loop: *What to
  submit next*, transplants, *Submittable* and model predictions run on worker threads (the
  longest stall fell from 2.3 s to under 0.5 s on a 50k vault). Quarter and pyramid counts
  from BRAIN are kept for 10 minutes and refreshed in the background. Tasks no longer wait on a
  busy catalog for dataset names.
- **Region Agnostic Lab without an LLM**: *Built-in shapes* (the default) writes 40 alphas a
  call from nineteen shapes over fields two or more chosen regions share, and favours shapes
  whose alphas score better. No key or budget needed.
- **Universe in every lab**: tick universes (none = every downloaded one) and *Random*, which
  draws each alpha's universe at random among those holding its fields. Region Agnostic gets a
  *Random* size; Evolution can run children in other universes too.
- **SuperAlpha**: seven more selections (unique and uncrowded, lean expressions, single
  source, fast but tradeable, quiet and slow, …) and six more combos (short and long IR, IR
  over volatility, uncrowded IR, …); tick which to run and which decays.
- **SuperAlpha repair**: near-miss SuperAlphas no longer fail with "Cannot read '.returns'";
  they get one-step changes to their settings, selection or combo, ordered by the failed check.
- **LLM labs** no longer default to translation, speech or image models (such as
  *live-translate*); those are marked *not for writing*.

## 2026-10-21 (evening)

- **Current Theme Lab** (Research Labs, no LLM): simulates only alphas that fit the running
  theme: its delay, datasets of its categories, one field per alpha, no group operators or
  grouping fields, Power Pool limits. Starts at once.
- **Themes as BRAIN announced them**: *D1 Power Pool Oct`26 2* (12–25 Oct: delay 1, one
  category of analyst, model or news, no PV1 group fields such as industry or sector; group
  operators over other data are fine) and the regular *GLB/D1 Turnover 15-30%* theme (12 Oct –
  8 Nov, x2.5): Regular and RA rows show *Fits theme*, with a *Fits a running theme* filter.
  The calendar takes regions, turnover bounds, multiplier and Power Pool or regular.
- **arXiv 429**: the app waits and retries, then tries again within the hour; restarts no longer
  re-read the feeds.
- **Faster**: `update.bat` + `start.bat` serve the built website at :8000; the vault is judged in
  the background at startup; the dashboard no longer scores every transplant.

## 2026-10-21 (morning)

- **What to submit next** (Alpha Types, Submittable and Needs re-check): each candidate's change
  to the combined IR of everything submitted, before and after cost, its correlation with the
  book and its highest with one submitted alpha. A guide: BRAIN's payment formula is not public.
- **Post-simulation models**: prod, Power Pool and self-correlation re-learned with Sharpe,
  fitness, turnover, returns, drawdown, margin and long/short counts. Alpha Types shows
  *Expected corr*; *Re-check top N* goes to the likeliest passes first.
- **Models steer the labs**: candidates the screen leaves out teach the search the models'
  estimate, so the next round is asked where passing alphas are expected (Settings).
- **Operators re-read daily** with the catalog sync.
- **Transplant filters** by dataset and category.
- **Free LLMs**: Cohere, Vercel AI Gateway, LM Studio added.
- **Cleaner app**: sidebar in workflow order (Set Up, Find Alphas, Fix and Improve, Submit,
  Track); Getting Started covers importing alphas and training models; Today's Openings has
  Find, Fix, Re-check, Submit buttons; Research Labs says which labs need an LLM. Repair,
  transplant and promotion tasks start at once and carry readable names on Tasks.

## 2026-10-21 (from your notes)

- **Your LLM subscriptions** through their makers' official CLIs: ChatGPT (Codex CLI,
  `codex exec`), Claude (Claude Code, `claude -p`) and Google AI (Antigravity CLI, `agy -p`).
  The app runs the unmodified tool you signed in to; it never sees the sign-in. Each needs a
  daily cap.

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
- **Ten more built-in template families** in the Template Lab (from one) and **ten more block templates** in Basic Template Research, shaped for less crowded signals
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
