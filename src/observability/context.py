"""Request-local identity; never shared mutable session state."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    chat_id: str
    request_id: str
    turn_id: str = None
    ingestion_id: str = None
    document_id: str = None
    attempt: int = 1
    retry_of_request_id: str = None

    @classmethod
    def create(cls, user_id, chat_id, **fields):
        return cls(user_id=user_id, chat_id=chat_id, request_id=uuid4().hex, **fields)


_current = ContextVar("logging_request", default=None)


def context_fields():
    context = _current.get()
    return asdict(context) if context else {}


@contextmanager
def request_context(context):
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)
