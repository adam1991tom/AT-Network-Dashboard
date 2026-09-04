from __future__ import annotations
from typing import Any

from app.database import connect


def list_recent(limit: int = 25) -> dict[str, Any]:
    con = connect()
    try:
        rows = con.execute("SELECT id,ts,category,summary,details FROM network_changes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        con.close()


def add(category: str, summary: str, details: str) -> dict[str, Any]:
    category = category.strip() or "General"
    summary = summary.strip()
    if not summary:
        return {"ok": False, "message": "Enter a summary of the change"}
    con = connect()
    try:
        cur = con.execute("INSERT INTO network_changes(category,summary,details) VALUES (?,?,?)", (category, summary, details.strip()))
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()
