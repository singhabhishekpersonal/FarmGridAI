"""Serializers for the chatbot app."""
from rest_framework import serializers

from apps.chatbot.models import ChatMessage, ChatSession, KnowledgeArticle, KnowledgeIntent


class ChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ["id", "farm", "language", "topic", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "intent", "sources", "is_fallback", "requires_human", "created_at"]
        read_only_fields = ["id", "created_at"]


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    language = serializers.CharField(max_length=10, required=False)


class KnowledgeArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeArticle
        fields = ["id", "topic", "title", "content", "tags", "is_active", "source"]
        read_only_fields = ["id"]


class KnowledgeIntentSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeIntent
        fields = ["id", "key", "patterns", "response", "suggestions"]
        read_only_fields = ["id"]