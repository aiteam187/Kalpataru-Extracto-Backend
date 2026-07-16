import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Select LLM Provider: 'groq' or 'azure_openai'
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower().strip()

BASE_REQUIRED_VARS = [
    "DOC_INTELLIGENCE_ENDPOINT",
    "DOC_INTELLIGENCE_KEY",
    # MS SQL Server (SSMS)
    "SQL_SERVER_HOST",
    "SQL_SERVER_DB",
    # Azure Blob Storage
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_BLOB_CONTAINER_NAME",
]

# Add LLM-specific variables conditionally to avoid blocking startup
if LLM_PROVIDER == "azure_openai":
    LLM_REQUIRED_VARS = [
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
    ]
else:
    LLM_REQUIRED_VARS = [
        "GROQ_API_KEY",
        "GROQ_API_URL",
        "GROQ_MODEL",
    ]

missing_vars = [var for var in (BASE_REQUIRED_VARS + LLM_REQUIRED_VARS) if not os.getenv(var)]
if missing_vars:
    raise RuntimeError(
        f"Missing required environment variable(s): {', '.join(missing_vars)}. "
        "Please check your .env file."
    )

# ── Azure Document Intelligence ──────────────────────────────────────────────
DOC_INTELLIGENCE_ENDPOINT = os.environ["DOC_INTELLIGENCE_ENDPOINT"]
DOC_INTELLIGENCE_KEY      = os.environ["DOC_INTELLIGENCE_KEY"]

# ── LLM Settings ─────────────────────────────────────────────────────────────
try:
    BASE_TEMPERATURE = float(os.getenv("BASE_TEMPERATURE", "0.1"))
except ValueError:
    BASE_TEMPERATURE = 0.1

# 1. Groq parameters (when provider is 'groq')
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL      = os.getenv("GROQ_API_URL", "")
GROQ_MODEL        = os.getenv("GROQ_MODEL", "")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# 2. Azure OpenAI parameters (when provider is 'azure_openai')
AZURE_OPENAI_API_KEY         = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT        = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")
AZURE_OPENAI_API_VERSION     = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

# Optional — tried only if the primary deployment fails every retry (e.g. an
# Azure-side outage on that specific deployment). Same Azure OpenAI resource,
# different model, so no separate endpoint/key is needed.
AZURE_OPENAI_FALLBACK_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT_NAME", "")

# ── MS SQL Server (SSMS) ─────────────────────────────────────────────────────
SQL_SERVER_HOST     = os.getenv("SQL_SERVER_HOST", "localhost")
SQL_SERVER_PORT     = int(os.getenv("SQL_SERVER_PORT", "1433"))
SQL_SERVER_DB       = os.getenv("SQL_SERVER_DB", "extracto_db")
SQL_SERVER_USER     = os.getenv("SQL_SERVER_USER", "")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD", "")
SQL_SERVER_DRIVER   = os.getenv("SQL_SERVER_DRIVER", "ODBC Driver 17 for SQL Server")

# ── Azure Blob Storage ────────────────────────────────────────────────────────
AZURE_STORAGE_CONNECTION_STRING = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
AZURE_BLOB_CONTAINER_NAME       = os.environ["AZURE_BLOB_CONTAINER_NAME"]