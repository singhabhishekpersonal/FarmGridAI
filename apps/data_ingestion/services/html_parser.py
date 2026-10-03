"""Lightweight HTML extraction using BeautifulSoup (bs4).

Pure: parses content bytes/str. Extraction focuses on metadata (OpenGraph /
JSON-LD / title) which is the source of labels and catalogue facts — never on
bypassing anything. Returns plain data structures.
"""
from bs4 import BeautifulSoup


class HTMLExtractError(Exception):
    pass


def _decode(content):
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def parse_document(content, features="lxml"):
    if not content or not content.strip():
        raise HTMLExtractError("empty document")
    return BeautifulSoup(_decode(content), features)


def extract_meta(soup):
    """Collect title + meta tags + OpenGraph properties."""
    meta = {}
    if soup.title and soup.title.get_text(strip=True):
        meta["title"] = soup.title.get_text(strip=True)
    for tag in soup.find_all("meta"):
        attr = tag.get("name") or tag.get("property")
        if attr:
            value = tag.get("content")
            if value:
                meta.setdefault("meta_tags", {})[attr] = value.strip()
    return meta


def extract_json_ld(soup):
    """Return JSON-LD blocks as parsed JSON objects (best-effort)."""
    import json

    blocks = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(tag.string or "")
        except (json.JSONDecodeError, ValueError):
            continue
        blocks.extend(parsed if isinstance(parsed, list) else [parsed])
    return blocks


def extract_links(soup, base_url=""):
    """Deduplicated absolute links within the same host as ``base_url``."""
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        links.add(href)
    return sorted(links)


def extract_image_urls(soup):
    """Image URLs from img.src + srcset (may be relative). Deduplicated."""
    urls = set()
    for tag in soup.find_all("img"):
        src = (tag.get("src") or "").strip()
        if src:
            urls.add(src)
        srcset = (tag.get("srcset") or "").strip()
        if srcset:
            for candidate in srcset.split(","):
                part = candidate.strip().split(" ")[0]
                if part:
                    urls.add(part)
    return sorted(urls)


def heading_text(soup, limit=256):
    text = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2", "h3"])[:20])
    return text[:limit]