from typing import List, Optional

from database.connection import execute_query, fetch_query, fetchrow_query

# Persisted in SQL Server (pending_sessions / pending_session_pages tables)
# rather than an in-process dict — an in-memory store was wiped on every
# restart/redeploy and wasn't shared across container replicas, which
# silently dropped the images for any extract() a user hadn't
# approved/rejected yet before that happened.
#
# The invoice is stored as a list of pages (pending_session_pages) since it
# can now be a multi-page (2-3 photo) document rather than exactly one image.


async def save_session(session_id: str, data: dict) -> None:
    await execute_query(
        """
        INSERT INTO pending_sessions
            (session_id, direction, front_name, front_bytes, back_name, back_bytes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        session_id,
        data.get("direction"),
        data.get("front_name"),
        data.get("front_bytes"),
        data.get("back_name"),
        data.get("back_bytes"),
    )

    for index, page in enumerate(data.get("challan_pages") or []):
        await execute_query(
            """
            INSERT INTO pending_session_pages (session_id, page_index, filename, image_bytes)
            VALUES (?, ?, ?, ?)
            """,
            session_id,
            index,
            page.get("name"),
            page.get("bytes"),
        )


async def get_session(session_id: str) -> Optional[dict]:
    row = await fetchrow_query(
        """
        SELECT direction, front_name, front_bytes, back_name, back_bytes
        FROM pending_sessions
        WHERE session_id = ?
        """,
        session_id,
    )
    if not row:
        return None

    page_rows = await fetch_query(
        """
        SELECT filename, image_bytes
        FROM pending_session_pages
        WHERE session_id = ?
        ORDER BY page_index ASC
        """,
        session_id,
    )
    challan_pages = [
        {
            "name": p["filename"],
            "bytes": bytes(p["image_bytes"]) if p["image_bytes"] is not None else None,
        }
        for p in page_rows
    ]

    return {
        "direction": row["direction"],
        "challan_pages": challan_pages,
        "front_name": row["front_name"],
        "front_bytes": bytes(row["front_bytes"]) if row["front_bytes"] is not None else None,
        "back_name": row["back_name"],
        "back_bytes": bytes(row["back_bytes"]) if row["back_bytes"] is not None else None,
    }


async def delete_session(session_id: str) -> None:
    await execute_query("DELETE FROM pending_session_pages WHERE session_id = ?", session_id)
    await execute_query("DELETE FROM pending_sessions WHERE session_id = ?", session_id)
