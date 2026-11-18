"""Web search → read the top pages → clean text for the LLM; search APIs instead of scraping Google, pages treated as untrusted."""

from __future__ import annotations

import concurrent.futures
import html as html_lib
import ipaddress
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from ..text import safe_print

# Honest User-Agent: Wikipedia and Cloudflare sites return 403 to fake browser UAs but accepted this one.
USER_AGENT = "MikaAssistant/2.0 (personal voice assistant for Windows; reads pages on the user's request)"
MAX_PAGE_BYTES = 1_500_000  # stop downloading huge pages; the article text is near the top anyway


@dataclass
class SearchResult:
    """One hit: title, URL, snippet, speakable source name, and the page text that was read."""

    title: str
    url: str
    snippet: str
    source: str
    content: str = ""


@dataclass
class SearchReport:
    """Results of one search plus which provider answered and which ones failed."""

    query: str
    provider: str
    results: list[SearchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SearchProvider(Protocol):
    """What every search backend implements."""

    name: str

    def is_configured(self) -> bool: ...

    def search(self, query: str, max_results: int) -> list[SearchResult]: ...


# Providers -----------------------------------------------------------------------------


class TavilySearch:
    """Tavily search API (built for LLM apps; needs TAVILY_API_KEY)."""

    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, client: httpx.Client, api_key_env: str = "TAVILY_API_KEY"):
        self.client = client
        self.api_key_env = api_key_env

    def is_configured(self) -> bool:
        """Only used when its API key is set."""
        return bool(os.environ.get(self.api_key_env))

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """POST /search and map the results."""
        response = self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {os.environ.get(self.api_key_env, '')}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": False},
        )
        response.raise_for_status()
        results = []
        for item in response.json().get("results", [])[:max_results]:
            url = str(item.get("url", ""))
            results.append(
                SearchResult(
                    title=_clean_snippet(item.get("title", "")),
                    url=url,
                    snippet=_clean_snippet(item.get("content", "")),
                    source=source_name(url),
                )
            )
        return results


class BraveSearch:
    """Brave Search API (independent index; needs BRAVE_API_KEY)."""

    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, client: httpx.Client, api_key_env: str = "BRAVE_API_KEY", country: str = ""):
        self.client = client
        self.api_key_env = api_key_env
        self.country = country

    def is_configured(self) -> bool:
        """Only used when its API key is set."""
        return bool(os.environ.get(self.api_key_env))

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """GET /web/search; uses Brave's publisher name as the source when available."""
        params: dict[str, Any] = {"q": query, "count": max_results}
        if self.country:
            params["country"] = self.country
        response = self.client.get(
            self.endpoint,
            params=params,
            headers={"Accept": "application/json", "X-Subscription-Token": os.environ.get(self.api_key_env, "")},
        )
        response.raise_for_status()
        results = []
        for item in (response.json().get("web") or {}).get("results", [])[:max_results]:
            url = str(item.get("url", ""))
            snippets = [item.get("description", "")] + list(item.get("extra_snippets") or [])
            profile_name = (item.get("profile") or {}).get("name")
            results.append(
                SearchResult(
                    title=_clean_snippet(item.get("title", "")),
                    url=url,
                    snippet=_clean_snippet(" ".join(str(s) for s in snippets if s)),
                    source=source_name(url, hint=profile_name),
                )
            )
        return results


def _ddgs_class() -> Any:
    """The DDGS class from `ddgs` (new name) or `duckduckgo_search` (old name), or None."""
    try:
        from ddgs import DDGS  # current package name

        return DDGS
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS  # older package name

        return DDGS
    except ImportError:
        return None


class DuckDuckGoSearch:
    """No-key fallback via the `ddgs` metasearch package; works out of the box but is less reliable."""

    name = "duckduckgo"

    def __init__(self, region: str = "id-id", timeout: float = 6, backends: list[str] | None = None):
        self.region = region
        self.timeout = timeout
        self.backends = backends or ["yahoo", "auto"]  # "duckduckgo" engine is DNS-blocked by some Indonesian ISPs

    def is_configured(self) -> bool:
        """Available whenever the package is installed."""
        return _ddgs_class() is not None

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Try each engine in order until one returns results."""
        ddgs_class = _ddgs_class()
        if ddgs_class is None:
            return []
        try:
            client = ddgs_class(timeout=int(self.timeout))
        except TypeError:
            client = ddgs_class()
        rows: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for backend in self.backends:
            try:
                rows = client.text(query, region=self.region, max_results=max_results, backend=backend) or []
            except Exception as exc:
                last_error = exc
                continue
            if rows:
                break
        if not rows and last_error is not None:
            raise last_error
        results = []
        for row in rows[:max_results]:
            url = str(row.get("href") or row.get("url") or "")
            results.append(
                SearchResult(
                    title=_clean_snippet(row.get("title", "")),
                    url=url,
                    snippet=_clean_snippet(row.get("body", "")),
                    source=source_name(url),
                )
            )
        return results


# Orchestration -------------------------------------------------------------------------


def _guard_request(request: httpx.Request) -> None:
    """Runs on every request and redirect, so a public page cannot bounce us to 127.0.0.1 or the LAN."""
    if not is_public_http_url(str(request.url)):
        raise httpx.RequestError(f"Alamat diblokir (bukan host publik): {request.url}", request=request)


def build_http_client(timeout: float) -> httpx.Client:
    """Shared HTTP client: timeouts, redirects, honest User-Agent, private-address guard."""
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 4.0)),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "id-ID,id;q=0.9,en;q=0.7"},
        event_hooks={"request": [_guard_request]},
    )


class WebSearcher:
    """Search with the first working provider (Tavily → Brave → ddgs), then read the top pages in parallel."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: httpx.Client | None = None,
        providers: list[SearchProvider] | None = None,
    ):
        cfg = config.get("web_search", {})
        self.max_results = int(cfg.get("max_results", 5))
        self.fetch_pages = int(cfg.get("fetch_pages", 3))
        self.page_chars = int(cfg.get("page_chars", 1200))
        self.timeout = float(cfg.get("timeout_seconds", 6))
        # Reading pages is optional enrichment: after this deadline a snippet beats a long silence.
        self.page_deadline = float(cfg.get("page_deadline_seconds", 3.5))
        self.client = client or build_http_client(self.timeout)
        if providers is None:
            providers = self._build_providers(cfg)
        self.providers = providers

    def _build_providers(self, cfg: dict[str, Any]) -> list[SearchProvider]:
        """Providers in the order configured in web_search.providers."""
        available: dict[str, SearchProvider] = {
            "tavily": TavilySearch(self.client),
            "brave": BraveSearch(self.client, country=str(cfg.get("brave_country", ""))),
            "duckduckgo": DuckDuckGoSearch(
                region=str(cfg.get("region", "id-id")),
                timeout=self.timeout,
                backends=list(cfg.get("ddgs_backends", ["yahoo", "auto"])),
            ),
        }
        order = cfg.get("providers", ["tavily", "brave", "duckduckgo"])
        return [available[name] for name in order if name in available]

    def search(self, query: str) -> SearchReport:
        """Never raises: an offline or failing search returns an empty report the LLM can explain."""
        report = SearchReport(query=query, provider="")
        for provider in self.providers:
            if not provider.is_configured():
                continue
            try:
                results = provider.search(query, self.max_results)
            except Exception as exc:
                report.errors.append(f"{provider.name}: {exc}")
                safe_print(f"[search] {provider.name} gagal: {exc}")
                continue
            results = [r for r in results if r.url]
            if results:
                report.provider = provider.name
                report.results = results
                break
        if report.results:
            self._read_pages(report.results[: self.fetch_pages])
            for result in report.results:
                if not result.content:
                    result.content = sanitize_untrusted(result.snippet)[: self.page_chars]
        return report

    def _read_pages(self, results: list[SearchResult]) -> None:
        """Fetch pages concurrently under one shared deadline; a slow site must not delay the answer."""
        if not results:
            return
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(results), thread_name_prefix="mika-fetch")
        futures = {pool.submit(self.fetch_text, result.url): result for result in results}
        try:
            done, _ = concurrent.futures.wait(futures, timeout=self.page_deadline)
            for future in done:
                try:
                    text = future.result()
                except Exception:
                    text = ""
                if len(text) > len(futures[future].snippet):
                    futures[future].content = text
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def fetch_text(self, url: str) -> str:
        """Download one public HTML page (size-capped) and return its cleaned main text, or "" on failure."""
        if not is_public_http_url(url):
            return ""
        try:
            with self.client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return ""
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text/plain" not in content_type:
                    return ""
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        break
                encoding = response.charset_encoding or "utf-8"
        except httpx.HTTPError:
            return ""
        page = b"".join(chunks).decode(encoding, errors="replace")
        text = page if "text/plain" in content_type else extract_main_text(page, url)
        return sanitize_untrusted(text)[: self.page_chars]


# Text helpers ---------------------------------------------------------------------------


def is_public_http_url(url: str) -> bool:
    """Only http(s) on public hosts: no localhost, LAN, file:, or other schemes."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a domain name; DNS-rebinding defence is out of scope for a desktop app


_SPECIAL_TOKEN = re.compile(r"<\|[^|>]{0,40}\|>|<\|")
_DETAIL_MARKER = re.compile(r"\[\s*detail\s*\]", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_untrusted(text: str) -> str:
    """Remove chat-template tokens (<|im_start|> could fake a system message) and our [DETAIL] marker from web text."""
    text = _SPECIAL_TOKEN.sub(" ", text)
    text = _DETAIL_MARKER.sub(" ", text)
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _clean_snippet(text: Any) -> str:
    """Strip HTML tags and entities from an API snippet, then sanitize it."""
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return sanitize_untrusted(html_lib.unescape(text))


def extract_main_text(page_html: str, url: str = "") -> str:
    """Article text without menus, ads, or scripts (trafilatura, else a stdlib fallback)."""
    try:
        import trafilatura

        text = trafilatura.extract(
            page_html, url=url or None, include_comments=False, include_tables=False, favor_precision=True
        )
        if text:
            return text
    except Exception:
        pass
    return _fallback_extract(page_html)


class _TextCollector(HTMLParser):
    """Collects visible text, skipping scripts, navigation, headers, and footers."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "iframe"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "article", "section", "br", "tr", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _fallback_extract(page_html: str) -> str:
    """Stdlib-only extractor used when trafilatura is not installed: keep paragraph-like lines."""
    collector = _TextCollector()
    try:
        collector.feed(page_html)
    except Exception:
        return ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(collector.parts).split("\n")]
    return "\n".join(line for line in lines if len(line) >= 40)


KNOWN_SOURCES = {
    "kompas.com": "Kompas",
    "kompas.id": "Kompas",
    "detik.com": "detikcom",
    "cnnindonesia.com": "CNN Indonesia",
    "cnbcindonesia.com": "CNBC Indonesia",
    "tempo.co": "Tempo",
    "liputan6.com": "Liputan6",
    "kumparan.com": "kumparan",
    "tribunnews.com": "Tribunnews",
    "antaranews.com": "Antara",
    "okezone.com": "Okezone",
    "sindonews.com": "SINDOnews",
    "republika.co.id": "Republika",
    "idntimes.com": "IDN Times",
    "suara.com": "Suara.com",
    "merdeka.com": "Merdeka",
    "bisnis.com": "Bisnis Indonesia",
    "kontan.co.id": "Kontan",
    "jpnn.com": "JPNN",
    "bmkg.go.id": "BMKG",
    "wikipedia.org": "Wikipedia",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "reuters.com": "Reuters",
    "apnews.com": "AP News",
    "theverge.com": "The Verge",
    "youtube.com": "YouTube",
    "github.com": "GitHub",
}
_SECOND_LEVEL = {"co", "ac", "go", "or", "web", "my", "sch", "net", "com", "org", "gov", "edu"}


def source_name(url: str, hint: str | None = None) -> str:
    """Speakable publisher name: "https://news.detik.com/x" -> "detikcom"."""
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    for domain, name in KNOWN_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return name
    if hint:
        return str(hint).strip()
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        label = parts[-3]
    elif len(parts) >= 2:
        label = parts[-2]
    else:
        label = host or "sumber web"
    return label.capitalize()
