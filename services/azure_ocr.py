import asyncio
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
import config


class AzureOCRService:
    @staticmethod
    def _analyze_sync(image_bytes: bytes) -> str:
        """
        Uses prebuilt-layout to extract text AND table structure.
        Table cells are serialized as TSV blocks so the LLM receives
        explicit row/column mapping — eliminates quantity bleeding between rows.
        """
        client = DocumentAnalysisClient(
            endpoint=config.DOC_INTELLIGENCE_ENDPOINT,
            credential=AzureKeyCredential(config.DOC_INTELLIGENCE_KEY)
        )

        poller = client.begin_analyze_document("prebuilt-layout", document=image_bytes)
        result = poller.result()

        parts = []

        # 1. Flat text content (paragraphs, key-value pairs outside tables)
        if hasattr(result, "content") and result.content:
            parts.append("=== DOCUMENT TEXT ===")
            parts.append(result.content)

        # 2. Tables — serialized as TSV with explicit row/col markers
        if hasattr(result, "tables") and result.tables:
            for t_idx, table in enumerate(result.tables):
                parts.append(f"\n=== TABLE {t_idx + 1} ({table.row_count} rows x {table.column_count} cols) ===")

                # Build a grid so we can print row by row
                grid = {}
                for cell in table.cells:
                    grid[(cell.row_index, cell.column_index)] = cell.content.strip()

                for row in range(table.row_count):
                    row_cells = [
                        grid.get((row, col), "")
                        for col in range(table.column_count)
                    ]
                    parts.append("\t".join(row_cells))

        return "\n".join(parts)

    @classmethod
    async def perform_ocr(cls, image_bytes: bytes) -> str:
        return await asyncio.to_thread(cls._analyze_sync, image_bytes)
