"""Admin configuration for the chatbot app."""
from django.contrib import admin

from apps.chatbot.models import ChatMessage, ChatSession, KnowledgeArticle, KnowledgeIntent


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ["role", "content", "intent", "is_fallback"]


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "farm", "language", "is_active", "created_at"]
    list_filter = ["language", "is_active"]
    inlines = [ChatMessageInline]


@admin.register(KnowledgeArticle)
class KnowledgeArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "topic", "is_active", "source"]
    list_filter = ["topic"]
    search_fields = ["title", "content", "tags"]


@admin.register(KnowledgeIntent)
class KnowledgeIntentAdmin(admin.ModelAdmin):
    list_display = ["key", "response"]
    search_fields = ["key"]