from typing import Dict, Any

# In-memory store: session_id → image bytes + filenames
# Cleared on approve or reject
_store: Dict[str, Any] = {}


def save_session(session_id: str, data: dict) -> None:
    _store[session_id] = data


def get_session(session_id: str) -> dict | None:
    return _store.get(session_id)


def delete_session(session_id: str) -> None:
    _store.pop(session_id, None)
