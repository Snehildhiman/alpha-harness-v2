"""Free research feeds, read as Atom or RSS.

The default is arXiv's quantitative-finance listing through its public API, which arXiv
offers for exactly this and asks only that callers stay at a request every few seconds. Any
other Atom or RSS feed the user adds in Settings is read the same way. Nothing behind a login
or a paywall, and no page scraping: a feed is a document its publisher put out to be read by
programs.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

#: arXiv's quantitative-finance categories that write about trading signals.
ARXIV_CATEGORIES = ("q-fin.TR", "q-fin.ST", "q-fin.PM", "q-fin.CP", "q-fin.GN")
#: Newest first, as many as one daily read is worth.
ARXIV_URL = (
    "https://export.arxiv.org/api/query?search_query="
    + "+OR+".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    + "&sortBy=submittedDate&sortOrder=descending&max_results=100"
)

_ATOM = "{http://www.w3.org/2005/Atom}"
_SPACE = re.compile(r"\s+")
_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    source: str
    title: str
    summary: str
    url: str
    authors: str
    published: datetime | None


def _text(node: Element | None) -> str:
    if node is None:
        return ""
    raw = "".join(node.itertext())
    return _SPACE.sub(" ", _TAGS.sub(" ", raw)).strip()


def _when(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except TypeError, ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _arxiv_key(identifier: str) -> str:
    """``http://arxiv.org/abs/2410.01234v2`` → ``arxiv:2410.01234``: versions are one paper."""
    tail = identifier.rstrip("/").rsplit("/", 1)[-1]
    return "arxiv:" + re.sub(r"v\d+$", "", tail)


def parse(document: str | bytes, source: str) -> list[Item]:
    """Every entry of an Atom or RSS document. Unreadable entries are skipped, not fatal."""
    root = ET.fromstring(document)  # noqa: S314 - a feed's own XML, no entity expansion in stdlib
    items: list[Item] = []
    if root.tag == f"{_ATOM}feed":
        for entry in root.findall(f"{_ATOM}entry"):
            identifier = _text(entry.find(f"{_ATOM}id"))
            link = next(
                (
                    str(a.get("href"))
                    for a in entry.findall(f"{_ATOM}link")
                    if a.get("rel") in (None, "alternate") and a.get("href")
                ),
                identifier,
            )
            title = _text(entry.find(f"{_ATOM}title"))
            if not title or not (identifier or link):
                continue
            key = _arxiv_key(identifier) if "arxiv.org" in identifier else identifier or link
            authors = ", ".join(
                _text(a.find(f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")
            )
            items.append(
                Item(
                    key=key,
                    source=source,
                    title=title,
                    summary=_text(entry.find(f"{_ATOM}summary"))
                    or _text(entry.find(f"{_ATOM}content")),
                    url=link,
                    authors=authors,
                    published=_when(_text(entry.find(f"{_ATOM}published")))
                    or _when(_text(entry.find(f"{_ATOM}updated"))),
                )
            )
        return items
    for entry in root.iter("item"):
        title = _text(entry.find("title"))
        link = _text(entry.find("link"))
        guid = _text(entry.find("guid")) or link
        if not title or not guid:
            continue
        items.append(
            Item(
                key=guid,
                source=source,
                title=title,
                summary=_text(entry.find("description")),
                url=link or guid,
                authors=_text(entry.find("author")),
                published=_when(_text(entry.find("pubDate"))),
            )
        )
    return items
