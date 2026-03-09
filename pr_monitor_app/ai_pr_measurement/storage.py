"""
SQLite persistence layer.

Every table stores provenance fields (source_api, raw_response_ref, status).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from .models import (
    BrandDemandRecord,
    EntityCheck,
    Observation,
    ReferralRecord,
    VisibilityIndexResult,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id                  TEXT PRIMARY KEY,
    date                TEXT,
    timestamp           TEXT,
    platform            TEXT,
    query_group         TEXT,
    query               TEXT,
    business_value      REAL,
    risk_level          REAL,
    brand_mentioned     INTEGER,
    brand_cited         INTEGER,
    own_domain_cited    INTEGER,
    citation_domains    TEXT,
    ai_answer_url_or_ref TEXT,
    prominence_score    INTEGER,
    sentiment_score     INTEGER,
    accuracy_flag       INTEGER,
    actionability       INTEGER,
    source_api          TEXT,
    raw_response_ref    TEXT,
    notes               TEXT,
    status              TEXT
);

CREATE TABLE IF NOT EXISTS entity_checks (
    id                TEXT PRIMARY KEY,
    timestamp         TEXT,
    check_type        TEXT,
    entity_name       TEXT,
    found             INTEGER,
    details           TEXT,
    source_api        TEXT,
    raw_response_ref  TEXT,
    status            TEXT,
    reason            TEXT
);

CREATE TABLE IF NOT EXISTS referral_records (
    id                TEXT PRIMARY KEY,
    timestamp         TEXT,
    date_range_start  TEXT,
    date_range_end    TEXT,
    source            TEXT,
    medium            TEXT,
    sessions          INTEGER,
    page_views        INTEGER,
    conversions       INTEGER,
    is_ai_source      INTEGER,
    source_api        TEXT,
    status            TEXT
);

CREATE TABLE IF NOT EXISTS brand_demand (
    id            TEXT PRIMARY KEY,
    timestamp     TEXT,
    keyword       TEXT,
    date          TEXT,
    interest_value INTEGER,
    source_api    TEXT,
    status        TEXT
);

CREATE TABLE IF NOT EXISTS visibility_index (
    id                        TEXT PRIMARY KEY,
    timestamp                 TEXT,
    scope                     TEXT,
    total_observations        INTEGER,
    ai_answer_sov             REAL,
    ai_citation_sov           REAL,
    mean_prominence           REAL,
    mean_accuracy             REAL,
    mean_sentiment            REAL,
    visibility_index          REAL,
    weighted_visibility_index REAL,
    status                    TEXT,
    reason                    TEXT
);
"""


class Storage:
    def __init__(self, db_path: str = "ai_pr_measurement.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        cur = self.conn.executescript(DDL)
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------
    def insert_observation(self, obs: Observation) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO observations
               (id, date, timestamp, platform, query_group, query,
                business_value, risk_level,
                brand_mentioned, brand_cited, own_domain_cited,
                citation_domains, ai_answer_url_or_ref,
                prominence_score, sentiment_score, accuracy_flag,
                actionability, source_api, raw_response_ref, notes, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                obs.id, obs.date, obs.timestamp, obs.platform,
                obs.query_group, obs.query, obs.business_value, obs.risk_level,
                obs.brand_mentioned, obs.brand_cited, obs.own_domain_cited,
                obs.citation_domains, obs.ai_answer_url_or_ref,
                obs.prominence_score, obs.sentiment_score, obs.accuracy_flag,
                obs.actionability, obs.source_api, obs.raw_response_ref,
                obs.notes, obs.status.value,
            ),
        )
        self.conn.commit()

    def insert_observations(self, observations: list[Observation]) -> None:
        for obs in observations:
            self.insert_observation(obs)

    def get_observations(
        self,
        date: Optional[str] = None,
        platform: Optional[str] = None,
        status: str = "SUCCESS",
    ) -> list[dict]:
        clauses = ["status = ?"]
        params: list = [status]
        if date:
            clauses.append("date = ?")
            params.append(date)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT * FROM observations WHERE {where} ORDER BY timestamp", params
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_observations(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM observations ORDER BY timestamp"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Entity checks
    # ------------------------------------------------------------------
    def insert_entity_check(self, ec: EntityCheck) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO entity_checks
               (id, timestamp, check_type, entity_name, found,
                details, source_api, raw_response_ref, status, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ec.id, ec.timestamp, ec.check_type, ec.entity_name,
                int(ec.found), json.dumps(ec.details), ec.source_api,
                ec.raw_response_ref, ec.status.value, ec.reason,
            ),
        )
        self.conn.commit()

    def get_entity_checks(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM entity_checks ORDER BY timestamp"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d["details"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Referral records
    # ------------------------------------------------------------------
    def insert_referral_record(self, rec: ReferralRecord) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO referral_records
               (id, timestamp, date_range_start, date_range_end,
                source, medium, sessions, page_views, conversions,
                is_ai_source, source_api, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.id, rec.timestamp, rec.date_range_start, rec.date_range_end,
                rec.source, rec.medium, rec.sessions, rec.page_views,
                rec.conversions, int(rec.is_ai_source), rec.source_api,
                rec.status.value,
            ),
        )
        self.conn.commit()

    def get_referral_records(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM referral_records ORDER BY timestamp"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Brand demand
    # ------------------------------------------------------------------
    def insert_brand_demand(self, rec: BrandDemandRecord) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO brand_demand
               (id, timestamp, keyword, date, interest_value, source_api, status)
               VALUES (?,?,?,?,?,?,?)""",
            (
                rec.id, rec.timestamp, rec.keyword, rec.date,
                rec.interest_value, rec.source_api, rec.status.value,
            ),
        )
        self.conn.commit()

    def get_brand_demand(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM brand_demand ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Visibility index
    # ------------------------------------------------------------------
    def insert_visibility_index(self, vi: VisibilityIndexResult) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO visibility_index
               (id, timestamp, scope, total_observations,
                ai_answer_sov, ai_citation_sov,
                mean_prominence, mean_accuracy, mean_sentiment,
                visibility_index, weighted_visibility_index,
                status, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                vi.id, vi.timestamp, vi.scope, vi.total_observations,
                vi.ai_answer_sov, vi.ai_citation_sov,
                vi.mean_prominence, vi.mean_accuracy, vi.mean_sentiment,
                vi.visibility_index, vi.weighted_visibility_index,
                vi.status.value, vi.reason,
            ),
        )
        self.conn.commit()

    def get_visibility_index_history(self, scope: str = "all") -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM visibility_index WHERE scope = ? ORDER BY timestamp",
            (scope,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # CSV export  (matches the template from the strategy doc)
    # ------------------------------------------------------------------
    def export_observations_csv(self, path: str) -> int:
        rows = self.get_all_observations()
        if not rows:
            return 0
        fieldnames = [
            "date", "platform", "query_group", "query",
            "brand_mentioned", "brand_cited", "own_domain_cited",
            "citation_domains", "ai_answer_url_or_ref",
            "prominence_score", "sentiment_score", "accuracy_flag", "notes",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def export_full_observations_csv(self, path: str) -> int:
        rows = self.get_all_observations()
        if not rows:
            return 0
        fieldnames = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)
