"""URL configuration for the chatbot app."""
from django.urls import path

from apps.chatbot.views import ChatAskView, ChatHistoryView, ChatSessionCreateView

urlpatterns = [
    path("sessions", ChatSessionCreateView.as_view(), name="chat-session-create"),
    path("sessions/<uuid:session_id>/ask", ChatAskView.as_view(), name="chat-ask"),
    path("sessions/<uuid:session_id>/messages", ChatHistoryView.as_view(), name="chat-history"),
]