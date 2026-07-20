"""
PostgreSQL query helpers for extraction_records.

All functions return either a parameterized SQL string + args tuple,
or operate directly on an asyncpg connection/pool passed in.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

TABLE = "extraction_records"


# ─────────────────────────────────────────────────────────────────────────────
# Record builders  (return dicts for easy inspection / logging)
# ─────────────────────────────────────────────────────────────────────────────

def new_extraction_record(
    direction: str,
    success: bool = True,
    document_type: str | None = None,
    ocr_text: str | None = None,
    extracted_data: dict | None = None,
    error_message: str | None = None,
    image_filename: str | None = None,
    vehicle_front_filename: str | None = None,
    vehicle_back_filename: str | None = None,
    folder_path: str | None = None,
    challan_image_url: str | None = None,
    vehicle_front_url: str | None = None,
    vehicle_back_url: str | None = None,
) -> dict:
    """Build a new extraction_records row dict."""
    return {
        "id": str(uuid.uuid4()),
        "entry_type": "automatic",
        "direction": direction,
        "document_type": document_type,
        "ocr_text": ocr_text,
        "extracted_data": extracted_data,
        "manual_fields": None,
        "success": success,
        "error_message": error_message,
        "image_filename": image_filename,
        "vehicle_front_filename": vehicle_front_filename,
        "vehicle_back_filename": vehicle_back_filename,
        "folder_path": folder_path,
        "challan_image_url": challan_image_url,
        "vehicle_front_url": vehicle_front_url,
        "vehicle_back_url": vehicle_back_url,
        # Returnable items start out "active" (still out) until explicitly
        # marked returned; irrelevant for inward/outward so left NULL there.
        "return_status": "active" if direction == "returnable" else None,
        "returned_at": None,
        "created_at": datetime.now(timezone.utc),
    }


def new_manual_entry_record(fields: list[dict]) -> dict:
    """Build a new extraction_records row for a manually-entered record."""
    return {
        "id": str(uuid.uuid4()),
        "entry_type": "manual",
        "direction": None,
        "document_type": "Manual Entry",
        "ocr_text": None,
        "extracted_data": None,
        "manual_fields": fields,
        "success": True,
        "error_message": None,
        "image_filename": None,
        "vehicle_front_filename": None,
        "vehicle_back_filename": None,
        "folder_path": None,
        "challan_image_url": None,
        "vehicle_front_url": None,
        "vehicle_back_url": None,
        "created_at": datetime.now(timezone.utc),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SQL helpers
# ─────────────────────────────────────────────────────────────────────────────

from database.connection import execute_query

async def insert_record(conn, record: dict) -> None:
    """INSERT a record dict into extraction_records in MS SQL Server."""
    # MS SQL Server uses BIT for boolean (1 = True, 0 = False)
    success_bit = 1 if record.get("success", True) else 0

    await execute_query(
        f"""
        INSERT INTO {TABLE} (
            id, entry_type, direction, document_type, ocr_text,
            extracted_data, manual_fields, success, error_message,
            image_filename, vehicle_front_filename, vehicle_back_filename,
            folder_path, challan_image_url, vehicle_front_url, vehicle_back_url,
            return_status, returned_at,
            created_at
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?
        )
        """,
        record["id"],
        record["entry_type"],
        record["direction"],
        record["document_type"],
        record["ocr_text"],
        json.dumps(record["extracted_data"]) if record["extracted_data"] is not None else None,
        json.dumps(record["manual_fields"]) if record["manual_fields"] is not None else None,
        success_bit,
        record["error_message"],
        record["image_filename"],
        record["vehicle_front_filename"],
        record["vehicle_back_filename"],
        record["folder_path"],
        record["challan_image_url"],
        record["vehicle_front_url"],
        record["vehicle_back_url"],
        # .get() — new_manual_entry_record() doesn't set these keys, and
        # they're irrelevant for manual entries (no direction there anyway).
        record.get("return_status"),
        record.get("returned_at"),
        record["created_at"],
    )



def row_to_dict(row) -> dict | None:
    """Convert an asyncpg Record to a plain dict."""
    if row is None:
        return None
    return dict(row)
