import uuid
import logging
from fastapi import APIRouter, File, UploadFile, Form
from typing import List, Optional

from models import ExtractionResponse
from services.azure_ocr import AzureOCRService
from services.groq_extraction import GroqExtractionService
from services import session_store

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_INVOICE_PAGES = 6


def validate_image_file(file: UploadFile) -> List[str]:
    errors = []
    if not file.content_type or not file.content_type.startswith("image/"):
        errors.append(
            f"File '{file.filename}' is not a valid image. "
            f"(Content-Type: '{file.content_type}')"
        )
    return errors


@router.post(
    "/extract",
    response_model=ExtractionResponse,
    summary="Upload invoice page(s) + both vehicle images and extract invoice data (preview only)",
    description=(
        "Upload vehicle front, vehicle back, and one or more invoice/challan page images "
        "(a multi-page invoice is treated as a single document spanning all pages). "
        "Only the invoice is extracted via OCR + LLM. "
        "Images are held in a pending_sessions row under the session_id — "
        "nothing is written to blob storage or the permanent extraction_records "
        "table yet. Call POST /approve to save everything, or POST /reject to discard."
    )
)
async def extract(
    challan_images:      List[UploadFile] = File(...),
    vehicle_front_image: UploadFile = File(...),
    vehicle_back_image:  UploadFile = File(...),
    direction: Optional[str] = Form(default="inward"),
):
    validation_messages = []

    if not challan_images:
        return ExtractionResponse(success=False, validation_messages=["At least one challan_images page is required."])
    if len(challan_images) > MAX_INVOICE_PAGES:
        return ExtractionResponse(
            success=False,
            validation_messages=[f"Too many invoice pages ({len(challan_images)}). Max is {MAX_INVOICE_PAGES}."]
        )

    # Validate all images (invoice pages + both vehicle images)
    for label, f in [("vehicle_front_image", vehicle_front_image), ("vehicle_back_image", vehicle_back_image)]:
        errs = validate_image_file(f)
        if errs:
            validation_messages.extend(errs)
    for i, f in enumerate(challan_images, start=1):
        errs = validate_image_file(f)
        if errs:
            validation_messages.extend([f"Page {i}: {e}" for e in errs])

    if validation_messages:
        return ExtractionResponse(success=False, validation_messages=validation_messages)

    # Normalize direction
    direction = (direction or "inward").strip().lower()
    if direction not in ("inward", "outward", "returnable"):
        direction = "inward"

    try:
        # Read all images into memory — nothing written to disk yet
        challan_bytes_list = [await f.read() for f in challan_images]
        front_bytes = await vehicle_front_image.read()
        back_bytes  = await vehicle_back_image.read()

        if not any(challan_bytes_list):
            return ExtractionResponse(
                success=False,
                validation_messages=["The challan_images are empty."]
            )

        # Azure OCR across all invoice pages, concatenated with page markers
        try:
            ocr_text = await AzureOCRService.perform_ocr_multi(challan_bytes_list)
        except Exception as e:
            logger.exception("Azure OCR failure")
            return ExtractionResponse(
                success=False,
                validation_messages=[f"Azure OCR extraction failed: {str(e)}"]
            )

        if not ocr_text.strip():
            return ExtractionResponse(
                success=False,
                ocr_text="",
                validation_messages=["No text could be extracted from the challan image(s)."]
            )

        # Groq LLM extraction across all invoice pages as one document
        try:
            extracted_data, document_type = await GroqExtractionService.extract_data(
                ocr_text=ocr_text,
                image_bytes_list=challan_bytes_list
            )
        except Exception as e:
            logger.exception("Groq LLM extraction failure")
            return ExtractionResponse(
                success=False,
                ocr_text=ocr_text,
                validation_messages=[f"Groq LLM data extraction failed: {str(e)}"]
            )

        # Persisted in SQL Server (pending_sessions) — zero blob/final-record
        # writes until approve, but survives restarts/redeploys/replica changes
        session_id = str(uuid.uuid4())
        await session_store.save_session(session_id, {
            "direction": direction,
            "challan_pages": [
                {
                    "name": f"challan_p{i+1}_{challan_images[i].filename or f'page{i+1}.jpg'}",
                    "bytes": b,
                }
                for i, b in enumerate(challan_bytes_list)
            ],
            "front_bytes": front_bytes,
            "back_bytes":  back_bytes,
            "front_name":  f"vehicle_front_{vehicle_front_image.filename or 'front.jpg'}",
            "back_name":   f"vehicle_back_{vehicle_back_image.filename or 'back.jpg'}",
        })

        return ExtractionResponse(
            success=True,
            session_id=session_id,
            extracted_data=extracted_data,
            document_type=document_type,
            ocr_text=ocr_text,
            validation_messages=validation_messages,
        )

    except Exception as e:
        logger.exception("Unexpected error in /extract")
        return ExtractionResponse(
            success=False,
            validation_messages=[f"An unexpected error occurred: {str(e)}"]
        )
