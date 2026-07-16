from __future__ import annotations
import sqlite3
import threading
from datetime import date
from policybot.models import (
    ArpRecord,
    ContractOfferingIdentity,
    PreApprovedRecord,
    DataClass,
    IagType,
)


class PreApprovedStore:
    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS arp (tool_name TEXT PRIMARY KEY, json TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS arp_offering ("
            "offering_key TEXT PRIMARY KEY, tool_name TEXT NOT NULL, json TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS decision ("
            "id TEXT PRIMARY KEY, tool_name TEXT, data_classification TEXT, "
            "iag_type TEXT, expires_at TEXT, json TEXT)"
        )
        self._db.commit()

    def save_arp(self, arp: ArpRecord) -> None:
        with self._lock:
            if arp.offering is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO arp_offering VALUES (?, ?, ?)",
                    (
                        arp.offering.cache_key(),
                        arp.tool_name.lower(),
                        arp.model_dump_json(),
                    ),
                )
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO arp VALUES (?, ?)",
                    (arp.tool_name.lower(), arp.model_dump_json()),
                )
            self._db.commit()

    def get_arp(
        self,
        offering: ContractOfferingIdentity | str,
    ) -> ArpRecord | None:
        with self._lock:
            if isinstance(offering, ContractOfferingIdentity):
                row = self._db.execute(
                    "SELECT json FROM arp_offering WHERE offering_key = ?",
                    (offering.cache_key(),),
                ).fetchone()
                if row is None and not any((
                    offering.plan,
                    offering.contract_version,
                    offering.effective_date,
                )):
                    # Migration douce des anciennes ARP indexées seulement par
                    # produit. Une offre explicitement précisée ne retombe jamais
                    # sur ce cache ambigu.
                    row = self._db.execute(
                        "SELECT json FROM arp WHERE tool_name = ?",
                        (offering.product.lower(),),
                    ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT json FROM arp_offering WHERE tool_name = ? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (offering.lower(),),
                ).fetchone()
                if row is None:
                    row = self._db.execute(
                        "SELECT json FROM arp WHERE tool_name = ?", (offering.lower(),)
                    ).fetchone()
        return ArpRecord.model_validate_json(row[0]) if row else None

    def save_decision(self, rec: PreApprovedRecord) -> None:
        with self._lock:
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
        today_iso = today.isoformat()
        with self._lock:
            row = self._db.execute(
                "SELECT json, expires_at FROM decision WHERE tool_name = ? "
                "AND data_classification = ? AND iag_type = ? "
                "AND (expires_at = '' OR expires_at >= ?) "
                "ORDER BY expires_at DESC",
                (tool_name.lower(), data_classification, iag_type, today_iso),
            ).fetchone()
        if not row:
            return None
        return PreApprovedRecord.model_validate_json(row[0])
