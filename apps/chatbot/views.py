"""API views for the chatbot app."""
from rest_framework.permissions import IsAuthenticated

from apps.api.mixins import ApiResponseMixin, FarmAccessMixin
from apps.chatbot.models import ChatSession
from apps.chatbot.serializers import ChatMessageSerializer, ChatRequestSerializer, ChatSessionSerializer
from apps.chatbot.services import ChatEngine


class ChatSessionCreateView(ApiResponseMixin, FarmAccessMixin):
    """Open a chat session, optionally scoped to one of the caller's farms.

    The farm is resolved by ownership rather than trusted from the payload, and
    an unknown farm id is reported as a 404 error envelope."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.farms.models import Farm

        farm = None
        farm_pk = request.data.get("farm")
        if farm_pk:
            farm = Farm.objects.filter(pk=farm_pk, user=request.user).first()
            if farm is None:
                return self.respond_error([{"field": "farm", "message": "Farm not found."}], status_code=404)
        language = request.data.get("language", "en")
        session = ChatSession.objects.create(user=request.user, farm=farm, language=language, created_by=request.user)
        return self.respond(data=ChatSessionSerializer(session).data, message="Session started.", status_code=201)


class ChatAskView(ApiResponseMixin, FarmAccessMixin):
    """Ask one question inside a session the caller owns.

    Retrieval is keyword-based over the knowledge base and no LLM is called; the
    question and the reply are both persisted as chat messages, and unmatched
    questions come back flagged as fallbacks needing a human."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = ChatSession.objects.filter(pk=session_id, user=request.user).first()
        if session is None:
            return self.respond_error([{"field": "session", "message": "Session not found."}], status_code=404)
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ChatEngine(session).ask(serializer.validated_data["message"], user=request.user)
        return self.respond(data=result, message="Answered.")


class ChatHistoryView(ApiResponseMixin, FarmAccessMixin):
    """The stored message transcript of a session, oldest first.

    Sessions belonging to another user are indistinguishable from missing ones,
    both returning a 404 error envelope."""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        session = ChatSession.objects.filter(pk=session_id, user=request.user).first()
        if session is None:
            return self.respond_error([{"field": "session", "message": "Session not found."}], status_code=404)
        messages = session.messages.order_by("created_at")
        return self.respond(data=ChatMessageSerializer(messages, many=True).data, message="History retrieved.")