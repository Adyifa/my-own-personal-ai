"""Headlines from public RSS feeds of Indonesian news sites: structured, key-less, no scraping."""

from __future__ import annotations

import concurrent.futures
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from .web_search import USER_AGENT, sanitize_untrusted, source_name

DEFAULT_FEEDS = [
    "https://www.antaranews.com/rss/terkini.xml",
    "https://www.cnnindonesia.com/nasional/rss",
    "https://www.republika.co.id/rss",
    "https://www.cnbcindonesia.com/news/rss",
]


@dataclass
class Headline:
    """One news item."""

    title: str
    link: str
    source: str


def parse_feed(xml_data: str | bytes) -> list[Headline]:
    """RSS 2.0 <item> or Atom <entry> → headlines; malformed feeds give []. Raw bytes let the XML
    declaration pick the encoding (expat in Python 3.11 also guards against entity-expansion bombs)."""
    try:
        root = ET.fromstring(xml_data.encode("utf-8") if isinstance(xml_data, str) else xml_data)
    except ET.ParseError:
        return []
    headlines = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title, link = "", ""
        for child in node:
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag == "title":
                title = child.text or ""
            elif child_tag == "link":
                link = child.text or child.attrib.get("href", "")
        title = sanitize_untrusted(html.unescape(re.sub(r"<[^>]+>", "", title))).strip()
        if title and link:
            headlines.append(Headline(title, link.strip(), source_name(link.strip())))
    return headlines


class NewsFeed:
    """Fetch several feeds in parallel under one deadline and interleave them for variety."""

    def __init__(self, config: dict[str, Any], *, client: httpx.Client | None = None):
        cfg = config.get("briefing", {})
        self.feeds = list(cfg.get("news_feeds", DEFAULT_FEEDS))
        self.timeout = float(cfg.get("news_timeout_seconds", 4))
        self._client = client

    @property
    def client(self) -> httpx.Client:
        """Created on first use (TLS setup is not free)."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return self._client

    def _fetch(self, url: str) -> list[Headline]:
        """One feed; errors give []."""
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return parse_feed(response.content)
        except (httpx.HTTPError, ValueError):
            return []

    def headlines(self, limit: int = 5) -> list[Headline]:
        """Top headlines, round-robin across feeds, without duplicates."""
        if not self.feeds:
            return []
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(self.feeds), thread_name_prefix="mika-news")
        futures = [pool.submit(self._fetch, url) for url in self.feeds]
        try:
            done, _ = concurrent.futures.wait(futures, timeout=self.timeout)
            per_feed = [future.result() for future in futures if future in done]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        merged, seen = [], set()
        for rank in range(max((len(items) for items in per_feed), default=0)):
            for items in per_feed:
                if rank < len(items) and items[rank].title.lower() not in seen:
                    seen.add(items[rank].title.lower())
                    merged.append(items[rank])
        return merged[:limit]


def short_title(title: str, max_words: int = 12) -> str:
    """Headlines are spoken; cut very long ones."""
    words = title.split()
    return title if len(words) <= max_words else " ".join(words[:max_words]) + "..."
