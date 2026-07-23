import sys
import uvicorn
from contextlib import asynccontextmanager

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from database.connection import init_pool, close_pool
import config  # noqa: F401 — validates env vars on import

from routes import (
    extract_router,
    upload_router,
    history_router,
    approve_router,
    reject_router,
    manual_entry_router,
)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan — PostgreSQL pool init on startup, close on shutdown
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    print("✅ Azure SQL Server (SSMS) pool ready.")
    yield
    await close_pool()
    print("🛑 Azure SQL Server (SSMS) pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# App init
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Extracto OCR & LLM Extraction Service",
    description="A lightweight OCR and structured extraction backend using Azure Document Intelligence and Groq LLM",
    version="1.0.0",
    docs_url=None,
    lifespan=lifespan,
)

# CORS — allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip JSON responses — /history list payloads are hundreds of KB of highly
# repetitive JSON that compresses ~85%; without this they crossed the wire
# uncompressed and transfer time dominated dashboard load.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# NOTE: /images static files mount removed — images are now served directly
# from Azure Blob Storage via public URLs stored in the database.


# ─────────────────────────────────────────────────────────────────────────────
# Swagger file-upload schema fix
# ─────────────────────────────────────────────────────────────────────────────
FILE_UPLOAD_SCHEMA = {
    "/extract": {
        "challan_image":       {"type": "string", "format": "binary", "description": "Invoice / Challan image (OCR extracted)"},
        "vehicle_front_image": {"type": "string", "format": "binary", "description": "Vehicle front-side image"},
        "vehicle_back_image":  {"type": "string", "format": "binary", "description": "Vehicle back-side image"},
        "direction":           {"type": "string", "enum": ["inward", "outward"], "default": "inward", "description": "Material movement direction"},
    },
    "/upload": {
        "vehicle_front_image": {"type": "string", "format": "binary", "description": "Vehicle front-side image"},
        "vehicle_back_image":  {"type": "string", "format": "binary", "description": "Vehicle back-side image"},
        "direction":           {"type": "string", "enum": ["inward", "outward"], "default": "inward", "description": "Material movement direction"},
    }
}


def _fix_schema_for_file_uploads(schema: dict) -> dict:
    paths = schema.get("paths", {})
    for path, overrides in FILE_UPLOAD_SCHEMA.items():
        try:
            post_op = paths[path]["post"]
            required_fields = [
                k for k, v in overrides.items()
                if v.get("format") == "binary"
                or (v.get("type") == "array" and v.get("items", {}).get("format") == "binary")
            ]
            post_op["requestBody"] = {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": required_fields,
                            "properties": overrides
                        }
                    }
                }
            }
        except KeyError:
            pass
    return schema


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version="3.0.3",
        description=app.description,
        routes=app.routes,
    )
    openapi_schema = _fix_schema_for_file_uploads(openapi_schema)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# ─────────────────────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────────────────────
app.include_router(extract_router)
app.include_router(upload_router)
app.include_router(history_router)
app.include_router(approve_router)
app.include_router(reject_router)
app.include_router(manual_entry_router)

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@4/swagger-ui.css",
        swagger_ui_parameters={"defaultModelsExpandDepth": -1}
    )


@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Extracto Backend API",
        "storage": "Azure Blob Storage",
        "database": "Azure PostgreSQL",
        "endpoints": {
            "extract":              "POST /extract                  — Upload all 3 images, extract invoice data (preview only)",
            "approve":              "POST /approve                  — Approve: upload images to Azure Blob + save to PostgreSQL",
            "reject":               "POST /reject                   — Reject: discard temp images, nothing saved",
            "history":              "GET  /history                  — List all automatic extraction records",
            "record":               "GET  /history/{id}             — Get single automatic record by ID",
            "manual_approve":       "POST /manual/approve           — Save key/value fields + image to manual_entry_records",
            "manual_reject":        "POST /manual/reject            — Discard manual entry",
            "manual_history":       "GET  /manual/history           — List all manual entry records",
            "manual_record":        "GET  /manual/history/{id}      — Get single manual record by ID",
            "manual_delete":        "DELETE /manual/history/{id}    — Delete manual record + Azure Blob image",
            "docs":                 "GET  /docs                     — Swagger UI",
        }
    }


if __name__ == "__main__":
    print("Starting Extracto backend server on http://0.0.0.0:8001 ...")
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)