"""Pipeline 08: Audit logs — XML to JSONB.

Source: EDU_DAU_DATA.EDU_NK_TongHop (1,248,820 rows, span 2018-2026).
Target: audit.audit_logs.

Migration policy: chỉ giữ N năm gần nhất theo ETL_AUDIT_KEEP_YEARS (default 3).

Source XML format (verified Đợt 3):
    <row Id="..." col1="v1" col2="v2" .../>
    <row Id="..." col1="v1" col2="v2" .../>
where row[0] = before, row[1] = after.

Convert sang JSONB: { "before": {...}, "after": {...} }.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..db import target_conn, stream_source
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


def parse_xml_history(xml_str: str | None) -> dict | None:
    """<row.../><row.../> → {'before': {...}, 'after': {...}}"""
    if not xml_str or not xml_str.strip():
        return None
    try:
        # Wrap multiple roots in single tag for ET to parse
        wrapped = f"<root>{xml_str}</root>"
        root = ET.fromstring(wrapped)
        rows = root.findall("row")
    except ET.ParseError:
        return None

    if not rows:
        return None

    def _attrs(elem) -> dict:
        return {k: v for k, v in elem.attrib.items()}

    if len(rows) == 1:
        return {"before": None, "after": _attrs(rows[0])}
    return {"before": _attrs(rows[0]), "after": _attrs(rows[1])}


def _classify(before: dict | None, after: dict | None) -> str:
    if before is None and after is not None:
        return "INSERT"
    if before is not None and after is None:
        return "DELETE"
    return "UPDATE"


def run() -> int:
    cutoff: datetime | None = None
    if settings.ETL_AUDIT_KEEP_YEARS > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * settings.ETL_AUDIT_KEEP_YEARS)
        logger.info(f"Filtering audit events newer than {cutoff.isoformat()}")
    else:
        logger.info("ETL_AUDIT_KEEP_YEARS=0 — keeping ALL audit events")

    if cutoff:
        query = (
            "SELECT Id, TableName, PrimaryKey, History, NguoiTao, NgayTao, "
            "NguoiCapNhat, NgayCapNhat "
            "FROM EDU_NK_TongHop "
            f"WHERE NgayTao >= '{cutoff.strftime('%Y-%m-%d')}' "
            "ORDER BY Id"
        )
    else:
        query = "SELECT Id, TableName, PrimaryKey, History, NguoiTao, NgayTao, NguoiCapNhat, NgayCapNhat FROM EDU_NK_TongHop ORDER BY Id"

    cols = [
        "table_name", "record_id", "operation",
        "old_value", "new_value",
        "changed_by", "changed_at", "legacy_event_id",
    ]

    with target_conn() as conn:
        if settings.ETL_TRUNCATE_BEFORE_LOAD:
            truncate_table(conn, "audit.audit_logs")

        # Optional: map legacy NguoiTao → users.id (skip if no users yet)
        # user_map = LegacyIdMapper(conn, "identity.users")  # via legacy_user_id

        total = 0
        skipped_parse = 0
        for batch in stream_source(settings.SOURCE_DB_DATA, query, settings.ETL_BATCH_SIZE):
            rows = []
            for src in batch:
                history = parse_xml_history(src.get("History"))
                if history is None:
                    skipped_parse += 1
                    continue
                operation = _classify(history.get("before"), history.get("after"))
                rows.append((
                    src.get("TableName") or "?",
                    src.get("PrimaryKey") or 0,
                    operation,
                    json.dumps(history.get("before"), ensure_ascii=False) if history.get("before") else None,
                    json.dumps(history.get("after"), ensure_ascii=False) if history.get("after") else None,
                    None,                                    # changed_by — TODO: resolve via users
                    src.get("NgayTao") or datetime.now(timezone.utc),
                    src["Id"],
                ))
            if rows:
                total += copy_rows(conn, "audit.audit_logs", cols, rows)
                conn.commit()
            logger.info(f"  audit_logs batch: {total:,} loaded, {skipped_parse:,} parse fails")

    logger.success(f"✓ audit.audit_logs: {total:,} rows ({skipped_parse:,} XML parse failures)")
    return total


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
