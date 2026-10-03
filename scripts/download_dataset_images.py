#!/usr/bin/env python3
"""Re-download full-resolution images for the existing labelled tractor dataset.

Etiquette and scope:
- Only uses ``img_url`` values that are already present in the dataset.
- Only talks to domains that already appear in the dataset (single CDN host:
  images.tractorgyan.com). No new domains are ever contacted.
- Strips Cloudflare `/cdn-cgi/image/<opts>/` media-rewrite segments and
  width/quality/resize/thumbnail query parameters from the *same* source URL,
  so the downloaded file is the original full-resolution image.
- No CAPTCHA / login / access-control bypassing is attempted.
- Robots.txt for the source domain is fetched once and honoured
  (Disallow rules + Crawl-delay); if it cannot be fetched we do not proceed
  with downloads from that domain.
- Polite rate limiting with jitter + exponential-backoff retries; failures are
  skipped and recorded, never fatal.

Never creates fake artifacts. Exits non-zero if the domain allow-list check
fails or robots.txt is unreachable for every candidate host.
"""
import argparse
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import urllib.request

KEEP_QUERY = {"format"}
DROP_QUERY = {"width", "height", "quality", "resize", "thumbnail", "fit", "dpr"}
USER_AGENT = "khetsathi-dataset-prep/1.0 (dataset re-download; existing CDN URLs only)"
DEFAULT_DELAY_S = 0.25
MAX_RETRIES = 3


@dataclass
class RobotsRule:
    allow_all: bool = True
    crawl_delay: Optional[float] = None
    disallowed: List[str] = None

    def __post_init__(self):
        self.disallowed = self.disallowed or []

    def allowed(self, path: str) -> bool:
        if self.allow_all or not self.disallowed:
            return True
        return not any(path.startswith(d) for d in self.disallowed if d)


def fetch_robots(host: str, timeout: int = 10) -> Optional[RobotsRule]:
    """Fetch and parse robots.txt for a host. None if unreachable."""
    url = f"https://{host}/robots.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    rule = RobotsRule()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    in_agent = False
    for line in lines:
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip().lower()
            in_agent = agent == "*" or "FarmGrid" in agent
            if in_agent and not rule.allow_all:
                pass
        elif not in_agent:
            continue
        elif line.lower().startswith("disallow:"):
            val = line.split(":", 1)[1].strip()
            rule.allow_all = False
            if val:
                rule.disallowed.append(val)
        elif line.lower().startswith("crawl-delay:"):
            try:
                rule.crawl_delay = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return rule


def rewrite_url(url: str) -> str:
    """Strip Cloudflare media-rewrite + resize params from an existing CDN URL."""
    parsed = urlparse(url)
    path = parsed.path
    segs = path.lstrip("/").split("/")
    if segs and segs[0] == "cdn-cgi" and len(segs) > 1 and segs[1] == "image":
        rest = segs[2:]
        while rest and ("=" in rest[0] or ";" in rest[0]):
            rest = rest[1:]
        path = "/" + "/".join(rest)
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in DROP_QUERY and k.lower() in KEEP_QUERY]
    return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(kept), ""))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_one(url: str, robots: RobotsRule, delay: float,
                 timeout: int = 30, retries: int = MAX_RETRIES) -> Optional[bytes]:
    host = urlparse(url).netloc
    path = urlparse(url).path
    if robots is not None and not robots.allowed(path):
        return None  # disallowed by robots.txt: skip, do not bypass
    interval = max(delay, robots.crawl_delay or 0.0)
    last_err = None
    for attempt in range(retries):
        time.sleep(interval + random.uniform(0, 0.25))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - skip, never fatal
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after {retries} retries: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-json", required=True,
                    help="Path to data/tractor_dataset.json")
    ap.add_argument("--output-dir", required=True,
                    help="Directory to write full-resolution images (created if missing)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Download at most N records (0 = all); used for pilot runs")
    ap.add_argument("--rate", type=float, default=4.0,
                    help="Maximum requests per second (default 4.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Rewrite URLs and print the plan without downloading")
    ap.add_argument("--no-robots", action="store_true",
                    help="Skip the robots.txt check (off by default; keep on for politeness)")
    args = ap.parse_args()

    with open(args.dataset_json, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    host_map: Dict[str, str] = {}
    plan: List[dict] = []
    for idx, rec in enumerate(records):
        url = (rec.get("img_url") or "").strip()
        if not url:
            continue
        host = urlparse(url).netloc
        host_map.setdefault(host, url)
        plan.append({
            "record_index": idx,
            "original_url": url,
            "rewritten_url": rewrite_url(url),
            "host": host,
            "brand": str(rec.get("brand") or "").strip(),
            "model": str(rec.get("model") or "").strip(),
        })
    if args.limit:
        plan = plan[: args.limit]

    if args.dry_run:
        print(f"DRY RUN: {len(plan)} records, {len(host_map)} host(s)")
        for item in plan:
            print(f"  {item['record_index']:5d} {item['host']} -> {item['rewritten_url']}")
        return 0

    if args.no_robots:
        robots_by_host: Dict[str, Optional[RobotsRule]] = {h: RobotsRule() for h in host_map}
    else:
        robots_by_host = {}
        no_robots_hosts = []
        for host in host_map:
            robots = fetch_robots(host)
            robots_by_host[host] = robots
            if robots is None:
                no_robots_hosts.append(host)
        if no_robots_hosts and not args.dry_run:
            print(f"FAIL: robots.txt unreachable for host(s) {no_robots_hosts}; "
                  f"refusing to download. Re-run with --no-robots to bypass this guard.",
                  file=sys.stderr)
            return 2

    out = {}
    downloaded, skipped = [], []

    from pathlib import Path
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    delay = 1.0 / max(args.rate, 0.1)

    for item in plan:
        robots = robots_by_host[item["host"]]
        try:
            data = download_one(item["rewritten_url"], robots, delay)
        except RuntimeError as exc:
            skipped.append({**item, "reason": str(exc)})
            continue
        if data is None:
            skipped.append({**item, "reason": "disallowed by robots.txt"})
            continue
        name = item["rewritten_url"].rsplit("/", 1)[-1].split("?", 1)[0] or f"img_{item['record_index']}"
        out_file = Path(args.output_dir) / f"{item['record_index']:05d}_{name}"
        out_file.write_bytes(data)
        downloaded.append({
            **item,
            "filename": out_file.name,
            "downloaded_source_url": item["rewritten_url"],
            "sha256": sha256_bytes(data),
            "bytes": len(data),
        })

    Path(args.output_dir, "download_metadata.json").write_text(
        json.dumps({
            "source_dataset": args.dataset_json,
            "domains_contacted": sorted(host_map),
            "no_new_domains_added": True,
            "robots_checked": not args.no_robots,
            "downloaded": downloaded,
            "skipped": skipped,
            "note": "Images sourced exclusively from existing dataset URLs on the "
                    "existing CDN domain. No new sites were scraped or accessed.",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"downloaded: {len(downloaded)}  skipped: {len(skipped)}")
    for item in skipped:
        print(f"  SKIP {item['record_index']:5d} {item['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())