import base64
import httpx
import json
import logging
from typing import Dict, Any, Tuple, Optional
import config
from prompts import SYSTEM_PROMPT, get_user_prompt

logger = logging.getLogger(__name__)


class GroqExtractionService:
    @staticmethod
    def _detect_image_mime(image_bytes: bytes) -> str:
        """Detect MIME type from image magic bytes."""
        if image_bytes[:4] == b'\x89PNG':
            return "image/png"
        if image_bytes[:3] in (b'\xff\xd8\xff',):
            return "image/jpeg"
        if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            return "image/webp"
        return "image/jpeg"  # safe default

    @staticmethod
    def _detect_document_type(extracted_data: dict) -> str:
        """
        Robustly detect document type from the dynamically extracted JSON.
        Checks multiple possible locations the LLM may have placed the type.
        """
        if not isinstance(extracted_data, dict):
            return "Unknown"

        # 1. Top-level document_type key (preferred by new universal prompt)
        top_level = (
            extracted_data.get("document_type")
            or extracted_data.get("type")
            or extracted_data.get("document_name")
            or extracted_data.get("doc_type")
        )
        if top_level and isinstance(top_level, str) and top_level.strip():
            return top_level.strip()

        # 2. Nested under document_metadata (legacy / some LLM responses)
        meta = extracted_data.get("document_metadata") or extracted_data.get("metadata")
        if isinstance(meta, dict):
            nested = (
                meta.get("document_type")
                or meta.get("type")
                or meta.get("document_name")
                or meta.get("doc_type")
            )
            if nested and isinstance(nested, str) and nested.strip():
                return nested.strip()

        # 3. Infer from known key patterns in the response
        if "invoice_no" in extracted_data or "gstin" in str(extracted_data).lower():
            return "Tax Invoice"
        if "gate_pass_no" in extracted_data or "security_gate_pass_no" in str(extracted_data).lower():
            return "Security Gate Pass"
        if "challan_no" in extracted_data:
            return "Delivery Challan"
        if "site_entry_stamp" in extracted_data and len(extracted_data) <= 3:
            return "Entry Stamp"
        if "mtn_number" in str(extracted_data).lower():
            return "Material Transfer Note"
        if "weighbridge" in str(extracted_data).lower() or "gross_weight" in extracted_data:
            return "Weighbridge Slip"

        return "Unknown"

    @staticmethod
    async def extract_data(
        ocr_text: str,
        image_bytes: Optional[bytes] = None
    ) -> Tuple[Dict[str, Any], str]:
        """
        Sends OCR text + image to Groq Vision LLM for full dynamic data extraction.

        Returns:
            (extracted_data_dict, document_type_string)
        """
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        user_text = get_user_prompt(ocr_text)

        # Build multimodal message if image is available
        if image_bytes:
            mime_type = GroqExtractionService._detect_image_mime(image_bytes)
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64_image}"

            user_content = [
                {
                    "type": "text",
                    "text": user_text
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_uri,
                        "detail": "high"
                    }
                }
            ]
            model = config.GROQ_VISION_MODEL
        else:
            # Fallback to text-only if no image provided
            user_content = user_text
            model = config.GROQ_MODEL

        # Configure endpoints and auth dynamically
        if config.LLM_PROVIDER == "azure_openai":
            url = f"{config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{config.AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={config.AZURE_OPENAI_API_VERSION}"
            headers = {
                "api-key": config.AZURE_OPENAI_API_KEY,
                "Content-Type": "application/json"
            }
            # Azure OpenAI matches the model key to the deployment name
            payload_model = config.AZURE_OPENAI_DEPLOYMENT_NAME
        else:
            url = config.GROQ_API_URL
            headers = {
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            payload_model = model

        system_role = "developer" if config.LLM_PROVIDER == "azure_openai" else "system"

        payload = {
            "model": payload_model,
            "messages": [
                {"role": system_role, "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
        }

        # Reasoning models (like GPT-5) on Azure OpenAI require max_completion_tokens and do not support temperature/max_tokens
        # GPT-5 uses internal reasoning tokens BEFORE producing output — 4096 is too small (causes finish_reason=length)
        if config.LLM_PROVIDER == "azure_openai":
            payload["max_completion_tokens"] = 16000  # reasoning tokens + output tokens combined
        else:
            payload["max_tokens"] = 8192
            payload["temperature"] = config.BASE_TEMPERATURE

        logger.info(f"Sending extraction request via provider: {config.LLM_PROVIDER}")

        async with httpx.AsyncClient(timeout=180.0) as client:  # 3 min timeout for large docs
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result_json = response.json()
            choices = result_json.get("choices", [])
            if not choices:
                raise ValueError(f"No completions returned from {config.LLM_PROVIDER} API response.")

            message = choices[0].get("message", {})
            content_str = message.get("content")
            refusal = message.get("refusal")
            finish_reason = choices[0].get("finish_reason", "")

            logger.debug(f"LLM response — finish_reason={finish_reason}, content_len={len(content_str or '')}, refusal={refusal}")

            # Reasoning models (GPT-5/o1/o3) may return None content with a refusal reason
            if not content_str:
                if refusal:
                    raise ValueError(f"LLM refused to process this request: {refusal}")
                if finish_reason == "content_filter":
                    raise ValueError("LLM response blocked by content safety filter.")
                raise ValueError(f"LLM returned empty content (finish_reason={finish_reason}). The document may be unreadable or unsupported.")

            # Strip markdown fences if the model returns them despite json_object mode
            content_str = content_str.strip()
            if content_str.startswith("```"):
                lines = content_str.split("\n")
                # Remove first line (```json or ```) and last line (```)
                content_str = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

            try:
                extracted_data = json.loads(content_str)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}\nRaw content: {content_str[:500]}")
                raise ValueError(f"LLM returned invalid JSON: {e}")

            document_type = GroqExtractionService._detect_document_type(extracted_data)
            logger.info(f"Extracted document type: {document_type}")

            return extracted_data, document_type
