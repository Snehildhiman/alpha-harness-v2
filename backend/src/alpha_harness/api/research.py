"""The research library: papers and posts from free feeds, for the LLM labs to draw on."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Query
from sqlalchemy import func, or_, select

from ..db.models import ResearchPaper
from ..schemas import Out
from .deps import State, refuse

router = APIRouter(prefix="/api/research", tags=["research"])


class Paper(Out):
    id: int
    source: str
    title: str
    summary: str
    url: str
    authors: str
    published: datetime | None
    starred: bool


class PaperPage(Out):
    total: int
    papers: list[Paper]
    #: When the feeds were last read, and what went wrong if anything did.
    last_read: datetime | None
    last_error: str | None
    sources: list[str]


def _paper(p: ResearchPaper) -> Paper:
    return Paper(
        id=p.id,
        source=p.source,
        title=p.title,
        summary=p.summary,
        url=p.url,
        authors=p.authors,
        published=p.published,
        starred=p.starred,
    )


@router.get("/papers")
async def papers(
    state: State,
    search: Annotated[str | None, Query()] = None,
    starred: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaperPage:
    """Kept papers, newest first; ``search`` matches title and summary."""
    where = []
    if search:
        like = f"%{search.strip()}%"
        where.append(or_(ResearchPaper.title.ilike(like), ResearchPaper.summary.ilike(like)))
    if starred:
        where.append(ResearchPaper.starred.is_(True))
    async with state.db.session() as session:
        total = await session.scalar(select(func.count()).select_from(ResearchPaper).where(*where))
        rows = (
            await session.scalars(
                select(ResearchPaper)
                .where(*where)
                .order_by(func.coalesce(ResearchPaper.published, ResearchPaper.fetched_at).desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    service = state.research
    return PaperPage(
        total=int(total or 0),
        papers=[_paper(p) for p in rows],
        last_read=service.last_read,
        last_error=service.last_error,
        sources=[name for name, _ in service.sources()],
    )


@router.post("/refresh")
async def refresh(state: State) -> dict[str, int]:
    """Read every feed now. Returns how many new papers each gave."""
    return await state.research.refresh()


@router.put("/papers/{paper_id}/star")
async def star(paper_id: int, state: State, on: Annotated[bool, Body(embed=True)]) -> Paper:
    async with state.db.session() as session:
        paper = await session.get(ResearchPaper, paper_id)
        if paper is None:
            raise refuse(404, "no_paper", "No such paper.")
        paper.starred = on
        await session.flush()
        return _paper(paper)
