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
    summary="Reject — discard the pending session, nothing saved",
    description=(
        "Called when the user rejects the extracted data. "
        "Deletes the pending session. Nothing is written to blob storage "
        "or the permanent extraction_records table."
    )
)
async def reject(session_id: str = Form(...)):
    await session_store.delete_session(session_id)
    logger.info(f"Rejected session {session_id} — cleared.")
    return RejectResponse(success=True, message="Session discarded.")
