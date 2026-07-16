import logging
from fastapi import APIRouter, Form
from pydantic import BaseModel

from services import session_store

logger = logging.getLogger(__name__)
router = APIRouter()


class RejectResponse(BaseModel):
    success: bool
    message: str = ""


@router.post(
    "/reject",
    response_model=RejectResponse,
    summary="Reject — discard images from memory, nothing saved",
    description=(
        "Called when the user rejects the extracted data. "
        "Clears the session from memory. Nothing is written to disk or DB."
    )
)
async def reject(session_id: str = Form(...)):
    session_store.delete_session(session_id)
    logger.info(f"Rejected session {session_id} — cleared from memory.")
    return RejectResponse(success=True, message="Session discarded.")
