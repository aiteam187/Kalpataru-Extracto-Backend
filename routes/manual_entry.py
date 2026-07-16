import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, UploadFile, Query
from typing import Optional
import aioodbc

from models import (
    ManualEntryApproveResponse,
    ManualEntryRecordOut,
    ManualHistoryResponse,
)
from database.connection import get_db, execute_query, fetch_query, fetchrow_query
from services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter()

MANUAL_TABLE = "manual_entry_records"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_manual_row(r: dict) -> ManualEntryRecordOut:
    created_at = r.get("created_at")
    if created_at and isinstance(created_at, datetime) and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    updated_at = r.get("updated_at")
    if updated_at and isinstance(updated_at, datetime) and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    fields = r.get("fields") or []
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except Exception:
            fields = []

    return ManualEntryRecordOut(
        id=str(r["id"]),
        fields=fields,
        image_filename=r.get("image_filename"),
        image_url=StorageService.sign_url(r.get("image_url")),
        blob_prefix=r.get("blob_prefix"),
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /manual/approve
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/manual/approve",
    response_model=ManualEntryApproveResponse,
    summary="Manual entry approve — save key/value fields + optional image to DB",
    description=(
        "Save manually-typed key/value pairs to manual_entry_records table. "
        "Optionally upload one invoice image — it will be stored in Azure Blob under "
        "manual/{YYYY-MM-DD}/{HH-MM-SS}/. "
        "Send as multipart/form-data: fields (JSON string) + image (file, optional)."
    ),
)
async def manual_approve(
    fields: str = Form(..., description='JSON array: [{"key": "...", "value": "..."}]'),
    image: Optional[UploadFile] = File(default=None, description="Invoice image (optional)"),
    pool: aioodbc.Pool = Depends(get_db),
):
    validation_messages = []

    # Parse fields JSON string
    try:
        raw_fields = json.loads(fields)
        if not isinstance(raw_fields, list):
            raise ValueError("fields must be a JSON array")
    except Exception as e:
        return ManualEntryApproveResponse(
            success=False,
            validation_messages=[f"Invalid fields JSON: {str(e)}"],
        )

    # Filter out blank keys
    clean_fields = [
        {"key": str(f.get("key", "")).strip(), "value": str(f.get("value", ""))}
        for f in raw_fields
        if str(f.get("key", "")).strip()
    ]

    if not clean_fields:
        return ManualEntryApproveResponse(
            success=False,
            validation_messages=["No fields to save — all rows had empty keys."],
        )

    # Upload image to Azure Blob (manual mode path)
    image_filename = None
    image_url = None
    blob_prefix = None

    if image and image.filename:
        # Validate image type
        if not image.content_type or not image.content_type.startswith("image/"):
            validation_messages.append(
                f"Warning: '{image.filename}' does not appear to be an image "
                f"(Content-Type: '{image.content_type}'). Skipping upload."
            )
        else:
            try:
                image_bytes = await image.read()
                if image_bytes:
                    safe_filename = image.filename or "invoice.jpg"
                    blob_prefix, image_url = StorageService.save_manual_file(
                        safe_filename, image_bytes
                    )
                    image_filename = safe_filename
                    logger.info(f"✅ Manual image uploaded: {image_url}")
                else:
                    validation_messages.append("Warning: uploaded image was empty, skipped.")
            except Exception as e:
                logger.exception("Image upload failed in /manual/approve")
                validation_messages.append(f"Warning: image upload failed: {str(e)}")

    # Save to manual_entry_records table
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await execute_query(
            f"""
            INSERT INTO {MANUAL_TABLE}
                (id, fields, image_filename, image_url, blob_prefix, created_at)
            VALUES
                (?, ?, ?, ?, ?, ?)
            """,
            record_id,
            json.dumps(clean_fields),
            image_filename,
            image_url,
            blob_prefix,
            now,
        )
        logger.info(f"✅ Manual entry saved — id={record_id}, fields={len(clean_fields)}, has_image={image_filename is not None}")
    except Exception as e:
        logger.exception("DB save failure in /manual/approve")
        return ManualEntryApproveResponse(
            success=False,
            validation_messages=[f"DB save failed: {str(e)}"],
        )

    return ManualEntryApproveResponse(
        success=True,
        extraction_id=record_id,
        image_url=image_url,
        blob_prefix=blob_prefix,
        validation_messages=validation_messages,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /manual/reject
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/manual/reject",
    summary="Manual entry reject — discard, nothing is saved",
)
async def manual_reject():
    return {"success": True, "message": "Manual entry discarded."}


# ─────────────────────────────────────────────────────────────────────────────
# GET /manual/history
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/manual/history",
    response_model=ManualHistoryResponse,
    summary="Get manual entry history",
    description="Fetch all manually-entered records with image URLs (paginated).",
)
async def get_manual_history(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    pool: aioodbc.Pool = Depends(get_db),
):
    try:
        # MS SQL Server limit/offset pagination syntax
        rows = await fetch_query(
            f"""
            SELECT * FROM {MANUAL_TABLE}
            ORDER BY created_at DESC
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """,
            offset, limit,
        )
        output = [_serialize_manual_row(dict(r)) for r in rows]
        return ManualHistoryResponse(success=True, total=len(output), records=output)
    except Exception:
        logger.exception("Error fetching manual history")
        return ManualHistoryResponse(success=False, total=0, records=[])


# ─────────────────────────────────────────────────────────────────────────────
# GET /manual/history/{record_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/manual/history/{record_id}",
    response_model=ManualEntryRecordOut,
    summary="Get single manual entry record by ID",
)
async def get_manual_record(
    record_id: str,
    pool: aioodbc.Pool = Depends(get_db),
):
    try:
        row = await fetchrow_query(
            f"SELECT * FROM {MANUAL_TABLE} WHERE id = ?", record_id
        )
        if not row:
            return {"success": False, "error": "Manual record not found"}
        return _serialize_manual_row(dict(row))
    except Exception as e:
        logger.exception("Error fetching manual record")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /manual/history/{record_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/manual/history/{record_id}",
    summary="Delete a manual entry record and its image from Azure Blob",
)
async def delete_manual_record(
    record_id: str,
    pool: aioodbc.Pool = Depends(get_db),
):
    try:
        row = await fetchrow_query(
            f"SELECT * FROM {MANUAL_TABLE} WHERE id = ?", record_id
        )
        if not row:
            return {"success": False, "error": "Manual record not found"}

        blob_prefix = dict(row).get("blob_prefix")

        # Delete DB record
        await execute_query(f"DELETE FROM {MANUAL_TABLE} WHERE id = ?", record_id)

        # Delete blobs
        deleted_blobs = []
        if blob_prefix:
            deleted_blobs = StorageService.delete_files_by_prefix(blob_prefix)

        return {
            "success": True,
            "message": f"Manual record {record_id} deleted",
            "deleted_files": deleted_blobs,
        }
    except Exception as e:
        logger.exception("Error deleting manual record")
        return {"success": False, "error": str(e)}
