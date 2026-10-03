"""robots.txt handling.

Uses the Python standard-library ``urllib.robotparser`` (a standards-based
parser, RFC 9309). Rules:

* if robots.txt is unavailable/ambiguous/unfetchable -> refuse to collect
  (manual review is required instead);
* if robots.txt denies the target path or any sub-part -> refuse;
* parsing is pure/offline: it operates on content bytes and URL strings.
"""
import io
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from apps.data_ingestion.services.urlutils import validate_scheme

USER_AGENT_KEY = "FarmGridAIResearchBot"


@dataclass
class RobotsDecision:
    retrieved: bool
    allows_target: bool
    reason: str = ""
    rules_summary: dict | None = None


def robots_url_for(base_url):
    """Standard robots.txt location for a base URL (origin root)."""
    parsed = validate_scheme(base_url)
    if not parsed.hostname:
        raise ValueError("robots url requires a hostname")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin.rstrip("/") + "/robots.txt"


def parse_robot_rules(content):
    """Parse robot rules (content + any base URL) into a RobotFileParser."""
    parser = RobotFileParser()
    parser.set_url("")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    parser.parse((line + "\n" for line in content.splitlines()))
    return parser


def robot_allows(parser, url, user_agent=None):
    """Consult a parsed robots parser for ``url`` (offline check)."""
    if parser is None:
        return False
    ua = user_agent or USER_AGENT_KEY
    return parser.can_fetch(ua, url)


def evaluate_robots(content, base_url, target_paths=None, user_agent=None):
    """Full offline robots evaluation.

    Returns :class:`RobotsDecision`. ``target_paths`` defaults to ``["/"]``.
    """
    parser = parse_robot_rules(content)
    if target_paths is None:
        target_paths = ["/"]
    ua = user_agent or USER_AGENT_KEY
    denied = []
    for path in target_paths:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        if not robot_allows(parser, url, user_agent=ua):
            denied.append(url)
    if denied:
        return RobotsDecision(retrieved=True, allows_target=False, reason=f"robot.txt denies: {denied}")
    return RobotsDecision(retrieved=True, allows_target=True)


def robots_is_unambiguous(content):
    """Best-effort sanity check that rules resolved for our UA (not just wildcard alone)."""
    if not content or not content.strip():
        return False
    return b"User-agent" in content if isinstance(content, bytes) else "User-agent" in content