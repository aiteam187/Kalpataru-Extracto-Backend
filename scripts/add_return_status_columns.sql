-- ============================================================================
-- Migration: add returnable-item status tracking to extraction_records
-- ============================================================================
-- Purpose:
--   Adds two new NULLable columns so the app can track whether a returnable
--   item (direction = 'returnable') is still out ("active") or has come back
--   ("returned"), plus the timestamp it was marked returned.
--
-- Safety:
--   - Purely additive: only ADDS two new columns, does not touch, rename,
--     or drop any existing column, table, index, or data.
--   - Both columns are NULLable with no DEFAULT constraint requiring a table
--     rewrite — every existing row will simply get NULL in both new columns.
--   - Does not lock the table for anything beyond a brief schema-metadata
--     update (standard ALTER TABLE ADD COLUMN behavior in SQL Server).
--   - No data is deleted, modified, or migrated by this script.
--
-- Run as: a login with ALTER permission on dbo.extraction_records
--   (the application's normal login only has SELECT/INSERT/UPDATE/DELETE
--   and cannot run this itself).
--
-- Database: Xtracto  (change below if your server names it differently)
-- ============================================================================

USE Xtracto;
GO

-- Guard: only add each column if it doesn't already exist, so this script
-- can be safely re-run without erroring.

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo'
      AND TABLE_NAME = 'extraction_records'
      AND COLUMN_NAME = 'return_status'
)
BEGIN
    ALTER TABLE dbo.extraction_records
        ADD return_status VARCHAR(20) NULL;
    -- Expected values: 'active' | 'returned' (NULL for non-returnable rows)
END
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo'
      AND TABLE_NAME = 'extraction_records'
      AND COLUMN_NAME = 'returned_at'
)
BEGIN
    ALTER TABLE dbo.extraction_records
        ADD returned_at DATETIME2 NULL;
    -- Set by the application the moment an item is marked 'returned'.
    -- Stays NULL until then, and while the item is still 'active'.
END
GO

-- Verify:
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME = 'extraction_records'
  AND COLUMN_NAME IN ('return_status', 'returned_at');
GO
