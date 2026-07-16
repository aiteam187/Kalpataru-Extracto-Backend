import struct
import logging
import aioodbc
import config
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Module-level pool — initialised in app lifespan
_pool: aioodbc.Pool | None = None

# ─────────────────────────────────────────────────────────────────────────────
# DATETIMEOFFSET converter (pyodbc type code -155 is unsupported natively)
# ─────────────────────────────────────────────────────────────────────────────
_SQL_DATETIMEOFFSET = -155


def _handle_datetimeoffset(dto_value: bytes) -> datetime | None:
    """
    Convert SQL Server DATETIMEOFFSET binary (20 bytes) → Python datetime.

    Binary layout (little-endian):
      6 x signed short  → year, month, day, hour, minute, second
      1 x unsigned int  → 100-nanosecond fractions
      2 x signed short  → tz_hour, tz_minute
    """
    try:
        if not dto_value or len(dto_value) != 20:
            return None
        year, month, day, hour, minute, second, frac_100ns, tz_h, tz_m = \
            struct.unpack("<6hI2h", dto_value)
        microsecond = (frac_100ns // 1000) % 1000000
        tz_total_minutes = tz_h * 60 + (tz_m if tz_h >= 0 else -abs(tz_m))
        tz = timezone(timedelta(minutes=tz_total_minutes))
        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=tz)
    except Exception as e:
        logger.error(f"Error decoding datetimeoffset bytes: {e}")
        return None


def _apply_converters(conn) -> None:
    """
    Register output converters on a raw pyodbc connection so that
    DATETIMEOFFSET columns (-155) are automatically converted to datetime.
    aioodbc wraps the raw connection — try common attribute names.
    """
    try:
        raw = getattr(conn, '_conn', None) \
              or getattr(conn, '_impl', None) \
              or conn
        raw.add_output_converter(_SQL_DATETIMEOFFSET, _handle_datetimeoffset)
    except Exception as exc:
        logger.debug(f"Could not add output converter: {exc}")


async def init_pool() -> aioodbc.Pool:
    """Create the aioodbc connection pool and ensure the schema exists."""
    global _pool

    # Build ODBC connection string
    conn_parts = [
        f"Driver={{{config.SQL_SERVER_DRIVER}}}",
        f"Server={config.SQL_SERVER_HOST},{config.SQL_SERVER_PORT}",
        f"Database={config.SQL_SERVER_DB}",
    ]
    if config.SQL_SERVER_USER:
        conn_parts.append(f"Uid={config.SQL_SERVER_USER}")
    if config.SQL_SERVER_PASSWORD:
        conn_parts.append(f"Pwd={config.SQL_SERVER_PASSWORD}")

    # For security and remote connections
    conn_parts.append("Encrypt=yes")
    conn_parts.append("TrustServerCertificate=yes")
    conn_parts.append("Connection Timeout=30")

    dsn = ";".join(conn_parts)
    logger.info(
        f"Connecting to SQL Server: {';'.join(p for p in conn_parts if not p.startswith('Pwd='))}"
    )

    _pool = await aioodbc.create_pool(
        dsn=dsn,
        minsize=2,
        maxsize=10,
        autocommit=True
    )
    logger.info("✅ SQL Server connection pool created.")

    # Auto-create all tables on first run (wrapped in try-except for restricted DDL users)
    try:
        await execute_query(_CREATE_EXTRACTION_TABLE_SQL)
        await execute_query(_CREATE_MANUAL_TABLE_SQL)
        await execute_query(_CREATE_PENDING_SESSIONS_TABLE_SQL)
        logger.info("✅ Schema verified / created (extraction_records + manual_entry_records + pending_sessions).")
    except Exception as e:
        logger.warning(
            f"⚠️ Table creation query failed: {e}. "
            "Assuming tables already exist or database user lacks DDL permissions."
        )

    # Opportunistic cleanup of abandoned pending sessions (extract() called but
    # never approved/rejected) so they don't accumulate indefinitely.
    try:
        await execute_query(
            "DELETE FROM pending_sessions WHERE created_at < DATEADD(HOUR, -24, GETUTCDATE())"
        )
    except Exception as e:
        logger.warning(f"⚠️ Stale pending_sessions cleanup skipped: {e}")

    return _pool


async def close_pool():
    """Close the connection pool gracefully on shutdown."""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        logger.info("🛑 SQL Server connection pool closed.")


def get_pool() -> aioodbc.Pool:
    """Return the module-level pool (must be initialised already)."""
    if _pool is None:
        raise RuntimeError("SQL Server pool is not initialised. Call init_pool() first.")
    return _pool


def get_db():
    """FastAPI dependency — returns the shared aioodbc pool."""
    return get_pool()


# ─────────────────────────────────────────────────────────────────────────────
# DB-API 2.0 / aioodbc Unified Query Wrappers
# ─────────────────────────────────────────────────────────────────────────────

async def execute_query(sql: str, *params) -> None:
    """Execute an INSERT, UPDATE, or DELETE query."""
    pool = get_pool()
    async with pool.acquire() as conn:
        _apply_converters(conn)
        async with conn.cursor() as cur:
            await cur.execute(sql, params)


async def fetch_query(sql: str, *params) -> list[dict]:
    """Fetch multiple rows as dictionaries."""
    pool = get_pool()
    async with pool.acquire() as conn:
        _apply_converters(conn)
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
            if not cur.description:
                return []
            columns = [col[0] for col in cur.description]
            return [dict(zip(columns, row)) for row in rows]


async def fetchrow_query(sql: str, *params) -> dict | None:
    """Fetch a single row as a dictionary, or None if no match."""
    pool = get_pool()
    async with pool.acquire() as conn:
        _apply_converters(conn)
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            if not row or not cur.description:
                return None
            columns = [col[0] for col in cur.description]
            return dict(zip(columns, row))


# ─────────────────────────────────────────────────────────────────────────────
# DDL — MS SQL Server (SSMS) Compatible Table Definitions
# ─────────────────────────────────────────────────────────────────────────────

# Table for AUTOMATIC entries (OCR + LLM extraction flow)
_CREATE_EXTRACTION_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='extraction_records' and xtype='U')
BEGIN
    CREATE TABLE extraction_records (
        id                      VARCHAR(100) PRIMARY KEY,
        entry_type              VARCHAR(50) NOT NULL DEFAULT 'automatic',
        direction               VARCHAR(50),
        document_type           VARCHAR(200),
        ocr_text                NVARCHAR(MAX),
        extracted_data          NVARCHAR(MAX),
        manual_fields           NVARCHAR(MAX),
        success                 BIT NOT NULL DEFAULT 1,
        error_message           NVARCHAR(MAX),
        image_filename          VARCHAR(500),
        vehicle_front_filename  VARCHAR(500),
        vehicle_back_filename   VARCHAR(500),
        folder_path             VARCHAR(500),
        challan_image_url       VARCHAR(1000),
        vehicle_front_url       VARCHAR(1000),
        vehicle_back_url        VARCHAR(1000),
        created_at              DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
        updated_at              DATETIME2
    )
END
"""

# Table for MANUAL entries (user-typed key/value pairs + optional invoice image)
_CREATE_MANUAL_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='manual_entry_records' and xtype='U')
BEGIN
    CREATE TABLE manual_entry_records (
        id              VARCHAR(100) PRIMARY KEY,
        fields          NVARCHAR(MAX) NOT NULL DEFAULT '[]',
        image_filename  VARCHAR(500),
        image_url       VARCHAR(1000),
        blob_prefix     VARCHAR(500),
        created_at      DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
        updated_at      DATETIME2
    );
END

IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='idx_manual_created_at' AND object_id=OBJECT_ID('manual_entry_records'))
BEGIN
    CREATE INDEX idx_manual_created_at ON manual_entry_records (created_at DESC);
END
"""

# Table for pending extract() sessions awaiting /approve or /reject.
# Previously held in an in-process dict, which was lost on every restart,
# redeploy, or when a request landed on a different container replica —
# persisting it here means it survives all of those.
_CREATE_PENDING_SESSIONS_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='pending_sessions' and xtype='U')
BEGIN
    CREATE TABLE pending_sessions (
        session_id      VARCHAR(100) PRIMARY KEY,
        direction       VARCHAR(50),
        challan_name    VARCHAR(500),
        challan_bytes   VARBINARY(MAX),
        front_name      VARCHAR(500),
        front_bytes     VARBINARY(MAX),
        back_name       VARCHAR(500),
        back_bytes      VARBINARY(MAX),
        created_at      DATETIME2 NOT NULL DEFAULT GETUTCDATE()
    )
END
"""
