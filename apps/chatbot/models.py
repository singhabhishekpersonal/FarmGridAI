"""Chatbot domain models: sessions, messages, and the knowledge base."""
from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.farms.models import Farm


class ChatSession(BaseModel):
    """A multi-turn support conversation for a farm."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sessions")
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="chat_sessions", null=True, blank=True)
    language = models.CharField(max_length=10, default="en")
    topic = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Session {self.pk} for {self.user_id}"


class ChatMessage(BaseModel):
    """A single assistant or user turn. ``is_fallback`` marks heuristic replies."""

    ROLE_CHOICES = [("user", "User"), ("assistant", "Assistant")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    intent = models.CharField(max_length=40, blank=True)
    sources = models.JSONField(default=list)
    is_fallback = models.BooleanField(default=False)
    requires_human = models.BooleanField(default=False)
    meta_json = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"


class KnowledgeArticle(BaseModel):
    """Curated FAQ / guidance content used for retrieval."""

    topic = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    content = models.TextField()
    tags = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=20, default="curated")

    class Meta:
        ordering = ["topic", "title"]

    def __str__(self):
        return self.title


class KnowledgeIntent(BaseModel):
    """Intent definition with matching patterns and a canned response."""

    KEY_CHOICES = [
        ("subsidy", "Subsidy"),
        ("solar", "Solar"),
        ("machine", "Machinery"),
        ("expense", "Expenses"),
        ("crop", "Crops"),
        ("energy", "Energy"),
        ("loan", "Loans"),
        ("maintenance", "Maintenance"),
        ("bigha", "Land units (bigha)"),
        ("hello", "Greeting"),
        ("fallback", "Fallback"),
    ]

    key = models.CharField(max_length=30, choices=KEY_CHOICES, unique=True)
    patterns = models.JSONField(default=list)
    response = models.TextField()
    suggestions = models.JSONField(default=list)
    # Matching is first-hit-wins, so without an explicit order a broad intent
    # can shadow a narrower one purely because its key sorts first. Higher wins.
    priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-priority", "key"]

    def __str__(self):
        return f"intent:{self.key}"