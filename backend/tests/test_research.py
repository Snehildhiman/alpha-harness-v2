"""Research feeds: Atom and RSS read into papers, kept once each, and briefed to the labs."""

import asyncio
from typing import Any

from alpha_harness.db.models import ResearchPaper
from alpha_harness.db.sqlite import Database
from alpha_harness.labs.params import PowerPoolParams
from alpha_harness.labs.power_pool import RESEARCH_HEAD, research_for
from alpha_harness.research.feeds import parse
from alpha_harness.research.service import ResearchService, brief

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2410.01234v2</id>
    <published>2026-10-18T17:59:00Z</published>
    <title>Analyst Revisions and  the Cross-Section
      of Returns</title>
    <summary>We show that upward revisions predict returns for six months.</summary>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
    <link href="http://arxiv.org/abs/2410.01234v2" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
  <item><title>Short interest is crowded</title><link>https://blog.example/short</link>
  <description>&lt;p&gt;Shorts pile into the same names.&lt;/p&gt;</description>
  <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_atom_and_rss_entries_become_papers() -> None:
    (paper,) = parse(ATOM, "arXiv q-fin")
    assert paper.key == "arxiv:2410.01234"  # versions are one paper
    assert paper.title == "Analyst Revisions and the Cross-Section of Returns"
    assert paper.authors == "A. Author, B. Author"
    assert paper.published is not None and paper.published.year == 2026
    (post,) = parse(RSS, "blog")
    assert post.key == "https://blog.example/short"
    assert post.summary == "Shorts pile into the same names."


def test_papers_are_kept_once_and_briefed_to_the_lab(tmp_path: Any) -> None:
    async def body() -> tuple[int, int, str]:
        db = Database(tmp_path / "h.db")
        await db.create_all()
        service = ResearchService(db)
        first = await service.store(parse(ATOM, "arXiv q-fin"))
        again = await service.store(parse(ATOM, "arXiv q-fin"))
        async with db.session() as session:
            paper = await session.get(ResearchPaper, 1)
            assert paper is not None
        run = PowerPoolParams(
            region="USA",
            delay=1,
            universes=["TOP3000"],
            neutralizations=["INDUSTRY"],
            research_ids=[1],
        )
        optimizer: Any = type("O", (), {"db": db})()
        text = await research_for(optimizer, run)
        await db.dispose()
        return first, again, text

    first, again, text = asyncio.run(body())
    assert (first, again) == (1, 0)
    assert text.startswith("Analyst Revisions")
    assert "six months" in text
    assert RESEARCH_HEAD.startswith("RESEARCH TO DRAW ON")


def test_brief_cuts_long_summaries() -> None:
    paper = ResearchPaper(key="k", source="s", title="T", summary="word " * 1000)
    assert len(brief([paper])) < 1600


def test_a_busy_feed_is_asked_again_then_left_for_later(monkeypatch: Any) -> None:
    import httpx2

    from alpha_harness.research import service

    monkeypatch.setattr(service, "BUSY_WAITS", (0.0,))
    calls: list[int] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(429) if len(calls) == 1 else httpx2.Response(200, content=ATOM)

    async def body() -> int:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(answer)) as client:
            response = await service._polite_get(client, "https://export.arxiv.org/api/query")
            return response.status_code

    assert asyncio.run(body()) == 200
    assert len(calls) == 2
