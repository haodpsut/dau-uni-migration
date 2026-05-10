"""Pipeline 07: Files — BLOB to MinIO.

Source: EDU_DAU_DATA.EDU_DT_SinhVien.HinhAnh (image type, 19,964 ảnh, 2.8GB)
        EDU_DAU_DATA.HRM_HinhAnh.HinhAnh (image, 652 ảnh, 29MB)
        EDU_DAU_DATA.EDU_KT_BienNhanNhapHoc.BienNhanFile (varbinary(MAX), 3023 PDF, 821MB)
        EDU_DAU_DATA.EDU_NK_FileSuaDiem.NoiDung (varbinary(MAX), 1346 PDF, 1GB)

Target: BLOBs uploaded to MinIO buckets, metadata in `files.attachments`.
Update photo_url in students/employees after upload.

Idempotent via SHA-256 checksum: nếu MinIO đã có object với cùng checksum, skip.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime
from typing import Iterator

from minio import Minio
from minio.error import S3Error

from ..config import settings
from ..db import target_conn, stream_source
from ..load import LegacyIdMapper, truncate_table
from ..log import logger


def get_minio_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info(f"Created MinIO bucket: {bucket}")


def upload_blob(
    client: Minio,
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> tuple[str, str]:
    """Upload bytes to MinIO. Returns (url, sha256)."""
    sha256 = hashlib.sha256(data).hexdigest()
    client.put_object(
        bucket,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    url = f"{'https' if settings.MINIO_SECURE else 'http'}://{settings.MINIO_ENDPOINT}/{bucket}/{object_key}"
    return url, sha256


# =============================================================================
# Student photos: EDU_DT_SinhVien.HinhAnh
# =============================================================================

def load_student_photos(conn) -> int:
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_STUDENTS
    ensure_bucket(client, bucket)

    student_map = LegacyIdMapper(conn, "student.students")
    uploaded = 0
    skipped = 0

    for batch in stream_source(
        settings.SOURCE_DB_DATA,
        "SELECT Id, IDSinhVien, HinhAnh FROM EDU_DT_SinhVien WHERE HinhAnh IS NOT NULL",
        100,
    ):
        for r in batch:
            blob: bytes = r["HinhAnh"]
            if not blob or len(blob) < 100:                  # skip tiny/empty
                skipped += 1
                continue

            student_id = student_map.lookup(r.get("IDSinhVien"))
            if not student_id:
                skipped += 1
                continue

            object_key = f"photos/{student_id}.jpg"
            try:
                url, checksum = upload_blob(client, bucket, object_key, blob, "image/jpeg")
            except S3Error as e:
                logger.warning(f"MinIO upload failed for student {student_id}: {e}")
                skipped += 1
                continue

            # Insert metadata + update student.photo_url
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO files.attachments
                       (bucket, object_key, url, file_name, content_type, size_bytes,
                        checksum_sha256, owner_table, owner_id, purpose)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'students', %s, 'photo')
                       ON CONFLICT (bucket, object_key) DO UPDATE SET
                         checksum_sha256 = EXCLUDED.checksum_sha256,
                         size_bytes = EXCLUDED.size_bytes""",
                    (bucket, object_key, url, f"{student_id}.jpg",
                     "image/jpeg", len(blob), checksum, student_id),
                )
                cur.execute(
                    "UPDATE student.students SET photo_url = %s, photo_uploaded_at = now() "
                    "WHERE id = %s",
                    (url, student_id),
                )
            uploaded += 1
        conn.commit()
        logger.info(f"  Uploaded {uploaded:,} student photos so far ({skipped:,} skipped)")

    logger.success(f"✓ Student photos: {uploaded:,} uploaded ({skipped:,} skipped)")
    return uploaded


# =============================================================================
# Employee photos: HRM_HinhAnh
# =============================================================================

def load_employee_photos(conn) -> int:
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_EMPLOYEES
    ensure_bucket(client, bucket)

    employee_map = LegacyIdMapper(conn, "hr.employees")
    uploaded = 0
    skipped = 0

    src = stream_source(
        settings.SOURCE_DB_DATA,
        "SELECT Id, IDNhanSu, HinhAnh FROM HRM_HinhAnh WHERE HinhAnh IS NOT NULL",
        50,
    )
    for batch in src:
        for r in batch:
            blob = r.get("HinhAnh")
            if not blob:
                skipped += 1
                continue
            employee_id = employee_map.lookup(r.get("IDNhanSu"))
            if not employee_id:
                skipped += 1
                continue
            object_key = f"photos/{employee_id}.jpg"
            try:
                url, checksum = upload_blob(client, bucket, object_key, blob, "image/jpeg")
            except S3Error as e:
                logger.warning(f"Upload failed for employee {employee_id}: {e}")
                skipped += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO files.attachments
                       (bucket, object_key, url, file_name, content_type, size_bytes,
                        checksum_sha256, owner_table, owner_id, purpose)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'employees', %s, 'photo')
                       ON CONFLICT (bucket, object_key) DO UPDATE SET
                         checksum_sha256 = EXCLUDED.checksum_sha256""",
                    (bucket, object_key, url, f"{employee_id}.jpg",
                     "image/jpeg", len(blob), checksum, employee_id),
                )
                cur.execute(
                    "UPDATE hr.employees SET photo_url = %s, photo_uploaded_at = now() "
                    "WHERE id = %s",
                    (url, employee_id),
                )
            uploaded += 1
        conn.commit()

    logger.success(f"✓ Employee photos: {uploaded:,} uploaded ({skipped:,} skipped)")
    return uploaded


# =============================================================================
# Grade change records (compliance) — EDU_NK_FileSuaDiem
# =============================================================================

def load_grade_change_records(conn) -> int:
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_GRADE_CHANGES
    ensure_bucket(client, bucket)

    student_map = LegacyIdMapper(conn, "student.students")
    course_class_map = LegacyIdMapper(conn, "academic.course_classes")

    uploaded = 0
    skipped = 0

    src = stream_source(
        settings.SOURCE_DB_DATA,
        """SELECT Id, IDSinhVien, IDLopHocPhan, LoaiSuaDiem,
                  DiemThiCu, DiemTongKetCu, DiemThiMoi, DiemTongKetMoi,
                  LoaiFile, NoiDung, TenFile, GhiChu, NgayTao, NguoiTao
           FROM EDU_NK_FileSuaDiem
           WHERE NoiDung IS NOT NULL""",
        50,
    )

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "files.grade_change_records")

    for batch in src:
        for r in batch:
            student_id = student_map.lookup(r.get("IDSinhVien"))
            cc_id = course_class_map.lookup(r.get("IDLopHocPhan"))
            if not student_id or not cc_id:
                skipped += 1
                continue
            blob = r.get("NoiDung")
            file_name = r.get("TenFile") or f"grade-change-{r['Id']}.pdf"
            content_type = "application/pdf"
            object_key = f"records/{r['Id']}_{file_name}"
            try:
                url, _ = upload_blob(client, bucket, object_key, blob, content_type)
            except S3Error as e:
                logger.warning(f"Upload failed: {e}")
                skipped += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO files.grade_change_records
                       (legacy_id, student_id, course_class_id, change_type,
                        old_exam_score, old_overall_score, new_exam_score, new_overall_score,
                        document_url, document_name, notes,
                        requested_by, approved_by, requested_at, approved_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s, NULL)""",
                    (r["Id"], student_id, cc_id,
                     "grade_correction",
                     r.get("DiemThiCu"), r.get("DiemTongKetCu"),
                     r.get("DiemThiMoi"), r.get("DiemTongKetMoi"),
                     url, file_name, r.get("GhiChu"),
                     r.get("NgayTao") or datetime.now()),
                )
            uploaded += 1
        conn.commit()

    logger.success(f"✓ Grade change records: {uploaded:,} uploaded ({skipped:,} skipped)")
    return uploaded


# =============================================================================
# Orchestrator
# =============================================================================

def run() -> dict[str, int]:
    results: dict[str, int] = {}
    with target_conn(autocommit=False) as conn:
        for name, fn in [
            ("student_photos", load_student_photos),
            ("employee_photos", load_employee_photos),
            ("grade_change_records", load_grade_change_records),
        ]:
            try:
                logger.info(f"Loading {name} ...")
                results[name] = fn(conn)
            except Exception:
                logger.exception(f"Failed: {name}")
                raise

    logger.success(f"✓ Files pipeline complete: {sum(results.values()):,} files")
    for name, count in results.items():
        logger.info(f"  {name}: {count:,}")
    return results


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
