from __future__ import annotations
import sqlite3
from datetime import date
from policybot.models import ArpRecord, PreApprovedRecord, DataClass, IagType


class PreApprovedStore:
    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS arp (tool_name TEXT PRIMARY KEY, json TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS decision ("
            "id TEXT PRIMARY KEY, tool_name TEXT, data_classification TEXT, "
            "iag_type TEXT, expires_at TEXT, json TEXT)"
        )
        self._db.commit()

    def save_arp(self, arp: ArpRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO arp VALUES (?, ?)",
            (arp.tool_name.lower(), arp.model_dump_json()),
        )
        self._db.commit()

    def get_arp(self, tool_name: str) -> ArpRecord | None:
        row = self._db.execute(
            "SELECT json FROM arp WHERE tool_name = ?", (tool_name.lower(),)
        ).fetchone()
        return ArpRecord.model_validate_json(row[0]) if row else None

    def save_decision(self, rec: PreApprovedRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO decision VALUES (?, ?, ?, ?, ?, ?)",
            (rec.id, rec.tool_name.lower(), rec.data_classification, rec.iag_type,
             rec.expires_at.isoformat() if rec.expires_at else "",
             rec.model_dump_json()),
        )
        self._db.commit()

    def find_decision(
        self, tool_name: str, data_classification: DataClass, iag_type: IagType,
        today: date | None = None,
    ) -> PreApprovedRecord | None:
        today = today or date.today()
        row = self._db.execute(
            "SELECT json, expires_at FROM decision WHERE tool_name = ? "
            "AND data_classification = ? AND iag_type = ? ORDER BY expires_at DESC",
            (tool_name.lower(), data_classification, iag_type),
        ).fetchone()
        if not row:
            return None
        _, expires = row
        if expires and date.fromisoformat(expires) < today:
            return None
        return PreApprovedRecord.model_validate_json(row[0])
