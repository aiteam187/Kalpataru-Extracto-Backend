import json
import logging
from fastapi import APIRouter, Form, Depends
from typing import Optional
import aioodbc

from models import ApproveResponse
from services.storage import StorageService
from services import session_store
from database.connection import get_db, execute_query
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

    # Get images (persisted in SQL Server, survives restarts/replica changes)
    session = await session_store.get_session(session_id)
    if not session:
        return ApproveResponse(
            success=False,
            validation_messages=[f"Session '{session_id}' not found. It may have already been approved/rejected, or it expired (pending sessions are cleared after 24 hours)."]
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

    # Upload the invoice page(s) + both vehicle images to Azure Blob Storage.
    # Invoice pages go first so the first URL returned is page 1, used below
    # as the backward-compat single challan_image_url column.
    challan_pages = session.get("challan_pages") or []
    try:
        files_to_save = (
            [(p["name"], p["bytes"]) for p in challan_pages] +
            [
                (session["front_name"], session["front_bytes"]),
                (session["back_name"],  session["back_bytes"]),
            ]
        )
        folder_path, saved_urls = StorageService.save_files(files_to_save, direction)
    except Exception as e:
        logger.exception("Storage failure in /approve")
        return ApproveResponse(
            success=False,
            validation_messages=[f"Failed to upload images to Azure Blob: {str(e)}"]
        )

    # Map saved URLs back to filenames for DB storage
    challan_urls = [u for u in saved_urls if "challan" in u]
    challan_url  = challan_urls[0] if challan_urls else None
    front_url    = next((u for u in saved_urls if "vehicle_front" in u), None)
    back_url     = next((u for u in saved_urls if "vehicle_back"  in u), None)

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

    # Record every invoice page's URL (not just the first) so the dashboard
    # can display and re-extract from the full multi-page document later.
    if challan_urls:
        try:
            for page_index, url in enumerate(challan_urls):
                await execute_query(
                    """
                    INSERT INTO extraction_record_pages (record_id, page_index, image_url)
                    VALUES (?, ?, ?)
                    """,
                    record["id"], page_index, url,
                )
        except Exception:
            logger.exception("Failed to save extraction_record_pages (non-fatal)")

    # Clear the pending session now that it's been persisted
    await session_store.delete_session(session_id)

    return ApproveResponse(
        success=True,
        extraction_id=str(record["id"]),
        folder_path=folder_path,
        saved_files=saved_urls,
        validation_messages=validation_messages
    )
