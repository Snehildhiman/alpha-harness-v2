"""The research library: feeds read on a schedule, kept for the LLM labs to draw on.

Papers are context, not alphas. An LLM Power Pool or Region Agnostic Lab task can be given
some, and each call then shows the model one of them beside the fields it may use: the model
carries the economic idea over to BRAIN's data, and the lab's own checks, the dedup, the
screen and the models decide what is worth simulating. A paper's idea being published (and so
crowded) is no reason to leave it out; the prompt asks for it to be carried by quieter data or
combined with something else.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx2
import structlog
from sqlalchemy import select

from ..db.models import ResearchPaper
from .feeds import ARXIV_URL, Item, parse

if TYPE_CHECKING:
    from ..db.sqlite import Database

log = structlog.get_logger(__name__)

#: Hours between reads. Feeds publish daily at most.
EVERY = timedelta(hours=12)
#: Seconds between looks at the clock.
CHECK_SECONDS = 900.0
#: arXiv asks API callers to leave a few seconds between requests.
PAUSE_SECONDS = 3.0
TIMEOUT = 30.0
#: Most characters of a summary a prompt carries.
SUMMARY_CHARS = 1500


#: Statuses that mean "not now": arXiv answers 429 when it is being asked too often.
BUSY = frozenset({429, 503})
#: Waits before asking a busy feed again within one read, honouring Retry-After up to the cap.
BUSY_WAITS = (5.0, 20.0)
RETRY_AFTER_CAP = 60.0
#: How soon a read that met a busy feed is tried again.
BUSY_RETRY = timedelta(hours=1)


async def _polite_get(client: httpx2.AsyncClient, url: str) -> httpx2.Response:
    """GET, waiting and asking again when the feed says it is busy."""
    response = await client.get(url)
    for wait in BUSY_WAITS:
        if response.status_code not in BUSY:
            break
        after = response.headers.get("retry-after", "")
        delay = min(float(after), RETRY_AFTER_CAP) if after.isdigit() else wait
        await asyncio.sleep(delay)
        response = await client.get(url)
    return response


class ResearchService:
    def __init__(self, db: Database) -> None:
        self.db = db
        #: Settings: on/off, and feeds beyond arXiv's.
        self.enabled = True
        self.feeds: list[str] = []
        self.last_read: datetime | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def configure(self, *, enabled: bool, feeds: list[str]) -> None:
        self.enabled = enabled
        self.feeds = feeds

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="research-feeds")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                due = self.last_read is None or datetime.now(UTC) - self.last_read >= EVERY
                if self.enabled and due:
                    await self.refresh()
            # A feed that is down must not end the schedule.
            except Exception:
                log.warning("research.tick_failed", exc_info=True)
            await asyncio.sleep(CHECK_SECONDS)

    def sources(self) -> list[tuple[str, str]]:
        return [("arXiv q-fin", ARXIV_URL), *((url, url) for url in self.feeds)]

    async def refresh(self) -> dict[str, int]:
        """Read every feed once; store what is new. Returns new items per source."""
        async with self._lock:
            found: dict[str, int] = {}
            errors: list[str] = []
            busy = False
            async with httpx2.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=True,
                headers={
                    # arXiv asks API callers to say who they are.
                    "User-Agent": "alpha-harness-v2/0.2 (personal research reader; "
                    "+https://github.com/Snehildhiman/alpha-harness-v2)"
                },
            ) as client:
                for index, (name, url) in enumerate(self.sources()):
                    if index:
                        await asyncio.sleep(PAUSE_SECONDS)
                    try:
                        response = await _polite_get(client, url)
                        if response.status_code in BUSY:
                            busy = True
                            errors.append(
                                f"{name} is busy right now (HTTP {response.status_code}); "
                                "the app tries again within the hour."
                            )
                            continue
                        response.raise_for_status()
                        items = parse(response.content, name)
                    except Exception as exc:  # noqa: BLE001 - one bad feed, not all
                        errors.append(f"{name}: {exc}")
                        log.warning("research.feed_failed", feed=name, error=str(exc)[:200])
                        continue
                    found[name] = await self.store(items)
            now = datetime.now(UTC)
            # A busy feed is tried again in an hour, not at the next twelve-hourly read.
            self.last_read = now - EVERY + BUSY_RETRY if busy else now
            self.last_error = "; ".join(errors) or None
            log.info("research.read", new=found)
            return found

    async def store(self, items: list[Item]) -> int:
        """Add the items not already kept. Returns how many were new."""
        if not items:
            return 0
        async with self.db.session() as session:
            known = set(
                (
                    await session.scalars(
                        select(ResearchPaper.key).where(
                            ResearchPaper.key.in_([i.key for i in items])
                        )
                    )
                ).all()
            )
            fresh = [i for i in {i.key: i for i in items}.values() if i.key not in known]
            session.add_all(
                ResearchPaper(
                    key=i.key[:512],
                    source=i.source[:64],
                    title=i.title,
                    summary=i.summary,
                    url=i.url,
                    authors=i.authors,
                    published=i.published,
                )
                for i in fresh
            )
        return len(fresh)


def brief(papers: list[ResearchPaper]) -> str:
    """The prompt section a lab call shows: titles and summaries, cut to size."""
    parts = []
    for paper in papers:
        summary = paper.summary
        if len(summary) > SUMMARY_CHARS:
            summary = summary[:SUMMARY_CHARS].rsplit(" ", 1)[0] + " …"
        parts.append(f"{paper.title}\n{summary}")
    return "\n\n".join(parts)


async def first_brief(db: Database, ids: list[int]) -> str:
    """The research the first call of a task would show, for a preview."""
    if not ids:
        return ""
    async with db.session() as session:
        paper = await session.get(ResearchPaper, ids[0])
    return brief([paper]) if paper is not None else ""
