import json
import logging
from fastapi import APIRouter, Form, Depends
from typing import Optional
import aioodbc

from models import ApproveResponse
from services.storage import StorageService
from services import session_store
from database.connection import get_db
from db_models.extraction import new_extraction_record, insert_record

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/approve",
    response_model=ApproveResponse,
    summary="Approve — save images to Azure Blob and extracted data to SQL Server",
    description=(
        "Called when the user approves the extracted data. "
        "Retrieves the 3 images from memory, uploads them to Azure Blob Storage, "
        "and saves extracted data to MS SQL Server."
    )
)
async def approve(
    session_id:     str            = Form(...),
    direction:      Optional[str]  = Form(default="inward"),
    document_type:  Optional[str]  = Form(default=None),
    ocr_text:       Optional[str]  = Form(default=None),
    extracted_data: Optional[str]  = Form(default=None),   # JSON string
    pool: aioodbc.Pool = Depends(get_db)
):
    validation_messages = []

    # Get images from memory
    session = session_store.get_session(session_id)
    if not session:
        return ApproveResponse(
            success=False,
            validation_messages=[f"Session '{session_id}' not found. Already approved/rejected or server restarted."]
        )

    # Normalize direction (prefer session's direction if not overridden)
    direction = (direction or session.get("direction") or "inward").strip().lower()
    if direction not in ("inward", "outward", "returnable"):
        direction = "inward"

    # Parse extracted_data JSON
    extracted_data_dict = None
    if extracted_data:
        try:
            extracted_data_dict = json.loads(extracted_data)
        except Exception:
            validation_messages.append("Warning: extracted_data JSON could not be parsed.")

    # Upload all 3 images to Azure Blob Storage
    try:
        files_to_save = [
            (session["challan_name"], session["challan_bytes"]),
            (session["front_name"],   session["front_bytes"]),
            (session["back_name"],    session["back_bytes"]),
        ]
        folder_path, saved_urls = StorageService.save_files(files_to_save, direction)
    except Exception as e:
        logger.exception("Storage failure in /approve")
        return ApproveResponse(
            success=False,
            validation_messages=[f"Failed to upload images to Azure Blob: {str(e)}"]
        )

    # Map saved URLs back to filenames for DB storage
    challan_url = next((u for u in saved_urls if "challan"       in u), None)
    front_url   = next((u for u in saved_urls if "vehicle_front" in u), None)
    back_url    = next((u for u in saved_urls if "vehicle_back"  in u), None)

    # Extract just the filename from the URL for backward-compat columns
    def _basename(url: str | None) -> str | None:
        return url.rsplit("/", 1)[-1] if url else None

    # Save extracted data to SQL Server
    try:
        record = new_extraction_record(
            direction=direction,
            success=True,
            document_type=document_type,
            ocr_text=ocr_text,
            extracted_data=extracted_data_dict,
            image_filename=_basename(challan_url),
            vehicle_front_filename=_basename(front_url),
            vehicle_back_filename=_basename(back_url),
            folder_path=folder_path,
            challan_image_url=challan_url,
            vehicle_front_url=front_url,
            vehicle_back_url=back_url,
        )
        await insert_record(None, record)
        logger.info(f"✅ Approved — record saved id={record['id']}")
    except Exception as e:
        logger.exception("DB save failure in /approve")
        return ApproveResponse(
            success=False,
            validation_messages=[f"DB save failed: {str(e)}"]
        )

    # Clear session from memory
    session_store.delete_session(session_id)

    return ApproveResponse(
        success=True,
        extraction_id=str(record["id"]),
        folder_path=folder_path,
        saved_files=saved_urls,
        validation_messages=validation_messages
    )
