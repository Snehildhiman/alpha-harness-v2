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
            async with httpx2.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "alpha-harness/0.1 (research reader)"},
            ) as client:
                for index, (name, url) in enumerate(self.sources()):
                    if index:
                        await asyncio.sleep(PAUSE_SECONDS)
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        items = parse(response.content, name)
                    except Exception as exc:  # noqa: BLE001 - one bad feed, not all
                        errors.append(f"{name}: {exc}")
                        log.warning("research.feed_failed", feed=name, error=str(exc)[:200])
                        continue
                    found[name] = await self.store(items)
            self.last_read = datetime.now(UTC)
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
