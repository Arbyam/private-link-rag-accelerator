"""Pydantic v2 DTOs that mirror `contracts/api-openapi.yaml` 1:1 (T042).

Naming and field constraints match the OpenAPI schemas exactly. Splits:
- error.py        : Error
- citation.py     : Citation
- turn.py         : Turn
- conversation.py : Conversation, ConversationSummary
- document.py     : DocumentMeta (+ nested Ingestion)
- chat.py         : ChatRequest
- admin.py        : AdminStats (+ nested LastIngestionRun)
- user.py         : Me (response of GET /me)
"""

from .admin import AdminStats, LastIngestionRun
from .chat import ChatRequest
from .citation import Citation, CitationScope
from .conversation import Conversation, ConversationSummary
from .document import DocumentIngestion, DocumentMeta, IngestionStatus
from .error import Error
from .turn import Turn, TurnRole
from .user import CurrentUser, Me, UserRole

__all__ = [
    "AdminStats",
    "ChatRequest",
    "Citation",
    "CitationScope",
    "Conversation",
    "ConversationSummary",
    "CurrentUser",
    "DocumentIngestion",
    "DocumentMeta",
    "Error",
    "IngestionStatus",
    "LastIngestionRun",
    "Me",
    "Turn",
    "TurnRole",
    "UserRole",
]
