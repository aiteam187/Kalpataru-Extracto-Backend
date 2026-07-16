from typing import Optional

from database.connection import execute_query, fetchrow_query

# Persisted in SQL Server (pending_sessions table) rather than an in-process
# dict — an in-memory store was wiped on every restart/redeploy and wasn't
# shared across container replicas, which silently dropped the images for
# any extract() a user hadn't approved/rejected yet before that happened.


async def save_session(session_id: str, data: dict) -> None:
    await execute_query(
        """
        INSERT INTO pending_sessions
            (session_id, direction, challan_name, challan_bytes, front_name, front_bytes, back_name, back_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        session_id,
        data.get("direction"),
        data.get("challan_name"),
        data.get("challan_bytes"),
        data.get("front_name"),
        data.get("front_bytes"),
        data.get("back_name"),
        data.get("back_bytes"),
    )


async def get_session(session_id: str) -> Optional[dict]:
    row = await fetchrow_query(
        """
        SELECT direction, challan_name, challan_bytes, front_name, front_bytes, back_name, back_bytes
        FROM pending_sessions
        WHERE session_id = ?
        """,
        session_id,
    )
    if not row:
        return None
    return {
        "direction": row["direction"],
        "challan_name": row["challan_name"],
        "challan_bytes": bytes(row["challan_bytes"]) if row["challan_bytes"] is not None else None,
        "front_name": row["front_name"],
        "front_bytes": bytes(row["front_bytes"]) if row["front_bytes"] is not None else None,
        "back_name": row["back_name"],
        "back_bytes": bytes(row["back_bytes"]) if row["back_bytes"] is not None else None,
    }


async def delete_session(session_id: str) -> None:
    await execute_query("DELETE FROM pending_sessions WHERE session_id = ?", session_id)
