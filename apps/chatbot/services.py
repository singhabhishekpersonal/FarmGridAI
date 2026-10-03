"""Deterministic knowledge-base chatbot.

No external LLM is required: the engine matches intents with keyword patterns
and retrieves knowledge articles by token overlap, then attaches full sources.
This keeps Chatbot answers honest, sourced and cheap. An LLM orchestrator can
be added behind the same ``ChatEngine`` interface.
"""
import re
from datetime import date

from apps.chatbot.models import ChatMessage, ChatSession, KnowledgeArticle, KnowledgeIntent


class ChatEngine:
    """Serve one user turn and return a structured, sourced reply."""

    def __init__(self, session: ChatSession):
        self.session = session

    # ------------------------------------------------------------------
    def _match_intent(self, text: str):
        # -priority first so a narrow intent wins over a broad one regardless of
        # how their keys happen to sort. Meta.ordering already encodes this.
        for intent in KnowledgeIntent.objects.filter(is_active=True).order_by("-priority", "key"):
            for pattern in intent.patterns or []:
                try:
                    if re.search(pattern, text, flags=re.IGNORECASE):
                        return intent
                except re.error:
                    continue
        fallback = KnowledgeIntent.objects.filter(key="fallback").first()
        return fallback

    # ------------------------------------------------------------------
    def _retrieve(self, text: str, limit=3):
        tokens = [t for t in re.split(r"\W+", text.lower()) if len(t) > 2]
        articles = KnowledgeArticle.objects.filter(is_active=True)
        scored = []
        for article in articles:
            hay = " ".join(article.tags + [article.topic, article.title.lower()])
            score = 0
            for tok in tokens:
                if tok in hay:
                    score += 1
                    continue
                stem = tok[:-3] + "y" if tok.endswith("ies") else (tok[:-1] if tok.endswith("s") and len(tok) > 3 else "")
                if stem and stem in hay:
                    score += 1
            scored.append((score, article))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [a for score, a in scored if score > 0][:limit], bool(len(tokens))

    # ------------------------------------------------------------------
    def ask(self, text: str, user=None):
        intent = self._match_intent(text)
        articles, _ = self._retrieve(text)
        sources = [
            {"article_id": str(a.id), "title": a.title, "topic": a.topic, "slug": a.slug}
            for a in articles
        ]

        is_fallback = intent is None or intent.key == "fallback"

        if intent is None:
            if articles:
                body = "\n\n".join(f"**{a.title}**\n{a.content[:600]}" for a in articles)
                reply = "I could not match a ready answer, but here is what may help:\n\n" + body
            else:
                reply = "I could not match your question to our knowledge base yet. Please rephrase, or ask a human advisor for verification."
            is_fallback = True
        elif intent.key == "fallback" or intent.key == "":
            reply = intent.response
        else:
            priority_articles = sorted(articles, key=lambda a: 0 if a.topic == intent.key else 1)
            article_hint = ""
            if priority_articles and priority_articles[0].topic == intent.key:
                article_hint = f"\n\nSee also: **{priority_articles[0].title}**"
            reply = intent.response + article_hint

        reply += (
            "\n\n*These are general educational pointers. Always verify scheme amounts, eligibility and prices with official sources before acting.*"
            if intent and intent.key in ("subsidy", "solar", "machine", "loan")
            else ""
        )

        ChatMessage.objects.create(session=self.session, role="user", content=text, created_by=user)
        assistant = ChatMessage.objects.create(
            session=self.session,
            role="assistant",
            content=reply,
            intent=intent.key if intent else "",
            sources=sources,
            is_fallback=is_fallback,
            requires_human=is_fallback,
            created_by=user,
        )
        return {
            "session_id": str(self.session.id),
            "reply": reply,
            "intent": intent.key if intent else "fallback",
            "sources": sources,
            "is_fallback": is_fallback,
            "requires_human": is_fallback,
            "suggestions": intent.suggestions if intent else [],
            "uses_llm": False,
        }