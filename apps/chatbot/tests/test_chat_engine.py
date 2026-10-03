import pytest

from apps.chatbot.models import ChatSession, KnowledgeArticle, KnowledgeIntent
from apps.chatbot.services import ChatEngine
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="bot", password="Str0ng!", phone="9876533333")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Bot Farm", area=4, unit="acre", state="Uttar Pradesh")


@pytest.fixture
def session(user, farm, db):
    return ChatSession.objects.create(user=user, farm=farm, language="en")


@pytest.fixture
def seeded_kb(db):
    KnowledgeIntent.objects.create(
        key="subsidy",
        patterns=["\\bsubsid", "\\bscheme\\b"],
        response="Subsidy guidance available.",
        suggestions=["Match subsidies"],
    )
    KnowledgeIntent.objects.create(
        key="fallback",
        patterns=[],
        response="Fallback reply.",
        suggestions=[],
    )
    KnowledgeArticle.objects.create(
        topic="subsidy",
        title="how subsidy matching works",
        slug="how-subsidy-matching-works",
        content="Credit based on profiles.",
        tags=["subsidy", "scheme"],
    )


def test_greeting_falls_back_gracefully(session, seeded_kb):
    reply = ChatEngine(session).ask("Hello there", user=session.user)
    assert reply["is_fallback"] is True
    assert session.messages.count() == 2


def test_subidy_match_returns_sourced_reply(session, seeded_kb):
    reply = ChatEngine(session).ask("What subsidies apply to my farm?", user=session.user)
    assert reply["intent"] == "subsidy"
    assert any(s["topic"] == "subsidy" for s in reply["sources"])
    assert session.messages.count() == 2  # user + assistant


def test_unknown_question_falls_back(session, seeded_kb):
    reply = ChatEngine(session).ask("xyzabc qwerty", user=session.user)
    assert reply["is_fallback"] is True
    assert reply["requires_human"] is True


def test_ask_without_any_intents_is_graceful(session, user):
    reply = ChatEngine(session).ask("magic question", user=user)
    assert reply["is_fallback"] is True
    assert session.messages.filter(role="assistant").count() == 1