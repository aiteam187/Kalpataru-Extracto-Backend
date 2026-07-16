import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from typing import Optional
import aioodbc

from database.connection import get_db, execute_query, fetch_query, fetchrow_query
from models import HistoryResponse, ExtractionRecordOut, UpdateRecordRequest
from services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter()

TABLE = "extraction_records"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_row(r: dict) -> ExtractionRecordOut:
    """Convert a SQL Server row dict to ExtractionRecordOut."""
    created_at = r.get("created_at")
    if created_at and isinstance(created_at, datetime) and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    updated_at = r.get("updated_at")
    if updated_at and isinstance(updated_at, datetime) and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    # extracted_data and manual_fields are NVARCHAR(MAX) JSON strings in SQL Server
    extracted_data = r.get("extracted_data")
    manual_fields  = r.get("manual_fields")

    if isinstance(extracted_data, str):
        try:
            extracted_data = json.loads(extracted_data)
        except Exception:
            extracted_data = None

    if isinstance(manual_fields, str):
        try:
            manual_fields = json.loads(manual_fields)
        except Exception:
            manual_fields = None

    # SQL Server returns success as boolean-like int (0/1) or bit, normalise to True/False
    success = bool(r.get("success", True))

    return ExtractionRecordOut(
        id=str(r["id"]),
        entry_type=r.get("entry_type", "automatic"),
        direction=r.get("direction"),
        document_type=r.get("document_type"),
        ocr_text=r.get("ocr_text"),
        extracted_data=extracted_data,
        manual_fields=manual_fields,
        success=success,
        error_message=r.get("error_message"),
        image_filename=r.get("image_filename"),
        vehicle_front_filename=r.get("vehicle_front_filename"),
        vehicle_back_filename=r.get("vehicle_back_filename"),
        folder_path=r.get("folder_path"),
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        challan_image_url=StorageService.sign_url(r.get("challan_image_url")),
        vehicle_front_url=StorageService.sign_url(r.get("vehicle_front_url")),
        vehicle_back_url=StorageService.sign_url(r.get("vehicle_back_url")),
    )


# CTE query definition to combine both automatic and manual entries
_COMBINED_QUERY_BASE = """
WITH combined_records AS (
    SELECT 
        id, 
        entry_type, 
        direction, 
        document_type, 
        ocr_text, 
        extracted_data, 
        manual_fields, 
        success, 
        error_message, 
        image_filename, 
        vehicle_front_filename, 
        vehicle_back_filename, 
        folder_path, 
        challan_image_url, 
        vehicle_front_url, 
        vehicle_back_url, 
        created_at, 
        updated_at
    FROM extraction_records

    UNION ALL

    SELECT 
        id, 
        'manual' AS entry_type, 
        NULL AS direction, 
        'Manual Entry' AS document_type, 
        NULL AS ocr_text, 
        NULL AS extracted_data, 
        fields AS manual_fields, 
        CAST(1 AS BIT) AS success,  -- Cast 1 to BIT to match column type in SQL Server
        NULL AS error_message, 
        image_filename, 
        NULL AS vehicle_front_filename, 
        NULL AS vehicle_back_filename, 
        blob_prefix AS folder_path, 
        image_url AS challan_image_url, 
        NULL AS vehicle_front_url, 
        NULL AS vehicle_back_url, 
        created_at, 
        updated_at
    FROM manual_entry_records
)
"""


# ─────────────────────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Get extraction history",
    description="Fetch past extraction records with image URLs (paginated, max 200 per request)."
)
async def get_history(
    direction: Optional[str] = Query(default=None, description="Filter: inward / outward"),
    success: Optional[bool]  = Query(default=None, description="Filter: true / false"),
    limit: int               = Query(default=50, le=200),
    offset: int              = Query(default=0),
    pool: aioodbc.Pool = Depends(get_db)
):
    try:
        conditions = []
        params = []

        if direction:
            conditions.append("direction = ?")
            params.append(direction.lower())
        if success is not None:
            # SQL Server BIT representation
            conditions.append("success = ?")
            params.append(1 if success else 0)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params += [offset, limit]  # OFFSET first, then LIMIT in fetch next

        sql = f"""
            {_COMBINED_QUERY_BASE}
            SELECT * FROM combined_records
            {where}
            ORDER BY created_at DESC
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """

        rows = await fetch_query(sql, *params)
        output = [_serialize_row(dict(r)) for r in rows]
        return HistoryResponse(success=True, total=len(output), records=output)

    except Exception:
        logger.exception("Error fetching history")
        return HistoryResponse(success=False, total=0, records=[])


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/all
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/all",
    response_model=HistoryResponse,
    summary="Get ALL extraction records (no pagination limit)",
    description="Fetch every extraction record at once, for full data export.",
)
async def get_all_history(
    direction: Optional[str] = Query(default=None, description="Filter: inward / outward"),
    success: Optional[bool]  = Query(default=None, description="Filter: true / false"),
    pool: aioodbc.Pool = Depends(get_db)
):
    try:
        conditions = []
        params = []

        if direction:
            conditions.append("direction = ?")
            params.append(direction.lower())
        if success is not None:
            conditions.append("success = ?")
            params.append(1 if success else 0)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"""
            {_COMBINED_QUERY_BASE}
            SELECT * FROM combined_records
            {where}
            ORDER BY created_at DESC
        """

        rows = await fetch_query(sql, *params)
        output = [_serialize_row(dict(r)) for r in rows]
        return HistoryResponse(success=True, total=len(output), records=output)

    except Exception:
        logger.exception("Error fetching all history")
        return HistoryResponse(success=False, total=0, records=[])


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/{record_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/{record_id}",
    response_model=ExtractionRecordOut,
    summary="Get single extraction record by ID",
)
async def get_record(
    record_id: str,
    pool: aioodbc.Pool = Depends(get_db)
):
    try:
        sql = f"""
            {_COMBINED_QUERY_BASE}
            SELECT * FROM combined_records WHERE id = ?
        """
        row = await fetchrow_query(sql, record_id)

        if not row:
            return {"success": False, "error": "Record not found"}

        return _serialize_row(dict(row))

    except Exception as e:
        logger.exception("Error fetching record")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /history/{record_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/history/{record_id}",
    summary="Delete an extraction record by ID",
)
async def delete_record(
    record_id: str,
    pool: aioodbc.Pool = Depends(get_db)
):
    try:
        # Check manual_entry_records first
        manual_row = await fetchrow_query(
            "SELECT * FROM manual_entry_records WHERE id = ?", record_id
        )

        if manual_row:
            blob_prefix = dict(manual_row).get("blob_prefix")
            await execute_query("DELETE FROM manual_entry_records WHERE id = ?", record_id)
            deleted_blobs = []
            if blob_prefix:
                deleted_blobs = StorageService.delete_files_by_prefix(blob_prefix)
            return {
                "success": True,
                "message": f"Manual record {record_id} deleted successfully",
                "deleted_files": deleted_blobs,
            }

        # Check extraction_records
        row = await fetchrow_query(
            "SELECT * FROM extraction_records WHERE id = ?", record_id
        )

        if not row:
            return {"success": False, "error": "Record not found"}

        row_dict = dict(row)
        folder_prefix = row_dict.get("folder_path")

        # Delete DB record first
        await execute_query(
            "DELETE FROM extraction_records WHERE id = ?", record_id
        )

        # Delete blobs from Azure Blob Storage
        deleted_blobs = []
        if folder_prefix:
            deleted_blobs = StorageService.delete_files_by_prefix(folder_prefix)

        return {
            "success": True,
            "message": f"Record {record_id} deleted successfully",
            "deleted_files": deleted_blobs,
        }

    except Exception as e:
        logger.exception("Error deleting record")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /history/{record_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.patch(
    "/history/{record_id}",
    summary="Update an extraction record",
)
async def update_record(
    record_id: str,
    body: UpdateRecordRequest,
    pool: aioodbc.Pool = Depends(get_db)
):
    try:
        set_clauses = []
        params = []

        if body.direction is not None:
            set_clauses.append("direction = ?")
            params.append(body.direction)
        if body.document_type is not None:
            set_clauses.append("document_type = ?")
            params.append(body.document_type)
        if body.extracted_data is not None:
            set_clauses.append("extracted_data = ?")
            params.append(json.dumps(body.extracted_data))
        if body.manual_fields is not None:
            set_clauses.append("manual_fields = ?")
            params.append(json.dumps([f.model_dump() for f in body.manual_fields]))

        if not set_clauses:
            row = await fetchrow_query(
                "SELECT * FROM extraction_records WHERE id = ?", record_id
            )
            if not row:
                return {"success": False, "error": "Record not found"}
            return {"success": True, "message": "Nothing to update", "record": _serialize_row(dict(row))}

        set_clauses.append("updated_at = ?")
        params.append(datetime.now(timezone.utc))
        params.append(record_id)

        sql = f"""
            UPDATE extraction_records
            SET {', '.join(set_clauses)}
            WHERE id = ?
        """
        await execute_query(sql, *params)
        row = await fetchrow_query("SELECT * FROM extraction_records WHERE id = ?", record_id)

        if not row:
            return {"success": False, "error": "Record not found"}

        return {"success": True, "message": "Record updated", "record": _serialize_row(dict(row))}

    except Exception as e:
        logger.exception("Error updating record")
        return {"success": False, "error": str(e)}