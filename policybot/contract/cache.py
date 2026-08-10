"""Cache local des analyses ARP, indexé par identité d'offre.

Anciennement `PreApprovedStore` : le nom mentait sur le contenu depuis que
les décisions préapprouvées ont été retirées du produit. Rien ici ne décide
quoi que ce soit — le cache évite seulement de repayer une recherche déjà
faite pour la même offre contractuelle.
"""
from __future__ import annotations

import sqlite3
import threading

from pydantic import ValidationError

from policybot.models import ArpRecord, ContractOfferingIdentity


class ArpCache:
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
        if not row:
            return None
        try:
            return ArpRecord.model_validate_json(row[0])
        except ValidationError:
            # Les caches antérieurs au schéma 2 portaient des faits typés et
            # ne doivent jamais être réinterprétés comme des constats.
            return None
