"""Standards-based robots.txt handling tests (pure, offline)."""
import pytest

from apps.data_ingestion.services.robots import (
    evaluate_robots,
    parse_robot_rules,
    robot_allows,
    robots_is_unambiguous,
    robots_url_for,
)


class TestRobotsURL:
    def test_standard_robots_url(self):
        assert robots_url_for("https://example.com/foo") == "https://example.com/robots.txt"

    def test_rejects_non_http_scheme(self):
        with pytest.raises(Exception):
            robots_url_for("file:///tmp/x")


class TestRobotsParsing:
    def test_allow_all_for_research_bot(self):
        content = b"User-agent: *\nAllow: /\n"
        result = evaluate_robots(content, "https://example.com", target_paths=["/static/", "/"])
        assert result.retrieved is True
        assert result.allows_target is True

    def test_deny_user_agent_group(self):
        content = b"User-agent: FarmGridAIResearchBot\nDisallow: /\nUser-agent: *\nAllow: /\n"
        result = evaluate_robots(content, "https://example.com", target_paths=["/"])
        assert result.allows_target is False

    def test_deny_specific_path(self):
        content = b"User-agent: *\nDisallow: /private/\n"
        result = evaluate_robots(content, "https://example.com", target_paths=["/private/photo.jpg"])
        assert result.allows_target is False

    def test_allow_specific_path(self):
        content = b"User-agent: *\nDisallow: /private/\n"
        result = evaluate_robots(content, "https://example.com", target_paths=["/public/photo.jpg"])
        assert result.allows_target is True

    def test_empty_robots_unambiguous_false(self):
        assert robots_is_unambiguous(b"") is False

    def test_blocked_robots_unambiguous_true(self):
        assert robots_is_unambiguous(b"User-agent: *\nDisallow: /\n") is True


class TestRobotAllows:
    def test_wildcard_allows_everything(self):
        parser = parse_robot_rules(b"User-agent: *\nAllow: /\n")
        assert robot_allows(parser, "https://example.com/x.jpg") is True

    def test_default_can_fetch_false_without_rule(self):
        parser = parse_robot_rules(b"")
        assert robot_allows(parser, "https://example.com/x.jpg") is True