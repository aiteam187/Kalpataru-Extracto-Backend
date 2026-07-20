from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class StoredFilesInfo(BaseModel):
    folder_path: str
    direction: str
    saved_files: List[str]


# ── Extract (preview only — nothing saved yet) ──────────────────────────────
class ExtractionResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None          # temp session ID, pass to /approve or /reject
    extracted_data: Optional[Dict[str, Any]] = None
    document_type: Optional[str] = None
    ocr_text: Optional[str] = None
    validation_messages: Optional[List[str]] = []


# ── Approve (save everything to DB + folders) ───────────────────────────────
class ApproveRequest(BaseModel):
    direction: str = "inward"
    document_type: Optional[str] = None
    ocr_text: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    challan_image_b64: Optional[str] = None        # base64 encoded
    challan_filename: Optional[str] = None
    vehicle_front_b64: Optional[str] = None        # base64 encoded
    vehicle_front_filename: Optional[str] = None
    vehicle_back_b64: Optional[str] = None         # base64 encoded
    vehicle_back_filename: Optional[str] = None


class ApproveResponse(BaseModel):
    success: bool
    extraction_id: Optional[str] = None
    folder_path: Optional[str] = None
    saved_files: Optional[List[str]] = []
    validation_messages: Optional[List[str]] = []


# ── Manual entry ──────────────────────────────────────────────────────────────
class ManualFieldPair(BaseModel):
    key: str
    value: str = ""


class ManualEntryApproveRequest(BaseModel):
    fields: List[ManualFieldPair] = []


class ManualEntryApproveResponse(BaseModel):
    success: bool
    extraction_id: Optional[str] = None
    image_url: Optional[str] = None          # Azure Blob URL of the uploaded image
    blob_prefix: Optional[str] = None        # Blob folder prefix (manual/{date}/{time}/)
    validation_messages: Optional[List[str]] = []


# ── Manual record output (for GET /manual/history) ───────────────────────────
class ManualEntryRecordOut(BaseModel):
    id: str
    fields: List[Dict[str, str]] = []        # [{"key": ..., "value": ...}, ...]
    image_filename: Optional[str] = None
    image_url: Optional[str] = None
    blob_prefix: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ManualHistoryResponse(BaseModel):
    success: bool
    total: int
    records: List[ManualEntryRecordOut] = []


# ── Upload response ──────────────────────────────────────────────────────────
class UploadResponse(BaseModel):
    success: bool
    direction: str
    folder_path: Optional[str] = None
    saved_files: Optional[List[str]] = []
    validation_messages: Optional[List[str]] = []


# ── History ──────────────────────────────────────────────────────────────────
class ExtractionRecordOut(BaseModel):
    id: str
    entry_type: str = "automatic"
    direction: Optional[str] = None
    document_type: Optional[str] = None
    ocr_text: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    manual_fields: Optional[List[Dict[str, str]]] = None
    success: bool
    error_message: Optional[str] = None
    image_filename: Optional[str] = None
    vehicle_front_filename: Optional[str] = None
    vehicle_back_filename: Optional[str] = None
    folder_path: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    challan_image_url: Optional[str] = None
    challan_image_urls: List[str] = []  # all invoice pages, in order (challan_image_url is page 1)
    vehicle_front_url: Optional[str] = None
    vehicle_back_url: Optional[str] = None
    return_status: Optional[str] = None  # "active" | "returned" — only meaningful when direction == "returnable"
    returned_at: Optional[str] = None    # set server-side the moment return_status flips to "returned"

    class Config:
        from_attributes = True


class HistoryResponse(BaseModel):
    success: bool
    total: int
    records: List[ExtractionRecordOut] = []


class UpdateRecordRequest(BaseModel):
    direction: Optional[str] = None
    document_type: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    manual_fields: Optional[List[ManualFieldPair]] = None
    return_status: Optional[str] = None  # "active" | "returned"