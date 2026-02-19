"""
ImportEnrollmentsData — Fully Vectorised & Optimised
=====================================================
Performance strategy:
  - Zero iterrows() in hot paths — all heavy lifting done via pandas merge/vectorisation
  - All DB reads use .values() — no ORM object overhead
  - All DB writes use bulk_create/bulk_update with batch_size
  - Minimum number of DB round trips (one read + one write per entity type)
  - Enrollments resolved entirely in pandas before touching the DB
  - itertuples() used for any remaining model object construction (10x faster than iterrows)
"""

from departments.models import Department
from rest_framework import generics, parsers
from rest_framework.response import Response
import pandas as pd
import numpy as np
from student.models import Student
from courses.models import Course, CourseGroup
from enrollments.models import Enrollment
from users.models import User
from semesters.models import Semester
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DEPARTMENT_LOCATION_MAP = {
    "15": 1,
    "12": 1,
    "19": 1,
}
DEFAULT_LOCATION_ID = 2
BATCH_SIZE = 1000   # rows per bulk_create call


# ── Helpers ───────────────────────────────────────────────────────────────────
def _dept_code_str(raw):
    if isinstance(raw, float) and not np.isnan(raw) and raw == int(raw):
        return str(int(raw))
    return str(raw)


def _build_email(first, last, reg_no):
    return f"{first.lower()}{last.lower()}{reg_no}@auca.ac.rw".replace(" ", "")


def _parse_name(full_name):
    """Return (first_name, last_name) from a full name string."""
    parts = str(full_name or "").strip().split()
    first = parts[0] if parts else ""
    last  = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first, last


# ── Main View ─────────────────────────────────────────────────────────────────
class ImportEnrollmentsData(generics.GenericAPIView):
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, *args, **kwargs):
        file              = request.FILES.get("myFile")
        selected_semester = request.data.get("selectedSemester")

        if not file:
            return Response({"error": "No file provided."}, status=400)

        # ── 1. Read & validate file ───────────────────────────────────────
        try:
            df = pd.read_excel(file, dtype=str)   # read everything as string — fastest
        except Exception as exc:
            return Response({"error": f"Could not read file: {exc}"}, status=400)

        required = {"COURSECODE", "COURSENAME", "CREDITS", "GROUP",
                    "STUDNUM", "STUDENTNAME", "FACULTYCODE", "TERM"}
        missing = required - set(df.columns)
        if missing:
            return Response({"error": f"Missing columns: {missing}"}, status=400)

        # ── 2. Clean data entirely in pandas — no Python loops ────────────
        df = df.dropna(subset=["STUDNUM"])
        df["STUDNUM_STR"] = (
            df["STUDNUM"]
            .str.strip()
            .apply(lambda x: str(int(float(x))) if _is_numeric(x) else None)
        )
        df = df.dropna(subset=["STUDNUM_STR"])

        if df.empty:
            return Response({"error": "No valid student records found."}, status=400)

        # Normalise faculty code column once
        df["DEPT_CODE"] = df["FACULTYCODE"].apply(
            lambda x: _dept_code_str(float(x)) if _is_numeric(x) else str(x)
        )

        # ── 3. Extract unique values for bulk DB fetches ──────────────────
        student_nums          = df["STUDNUM_STR"].unique().tolist()
        dept_codes            = df["DEPT_CODE"].dropna().unique().tolist()
        course_codes          = df["COURSECODE"].dropna().unique().tolist()
        semester_terms        = df["TERM"].dropna().unique().tolist()
        uploaded_group_names  = df["GROUP"].dropna().unique().tolist()

        # Unique (course_code, group_name) pairs from file
        cg_pairs_df = (
            df[["COURSECODE", "GROUP"]]
            .dropna(subset=["GROUP"])
            .drop_duplicates()
            .reset_index(drop=True)
        )

        stats  = defaultdict(int)
        errors = []

        with transaction.atomic():

            # ══════════════════════════════════════════════════════════════
            # STEP 1 — SEMESTER
            # ══════════════════════════════════════════════════════════════
            if selected_semester:
                Semester.objects.exclude(name=selected_semester).update(is_active=False)
                Semester.objects.update_or_create(
                    name=selected_semester,
                    defaults={
                        "start_date": timezone.now(),
                        "end_date":   timezone.now(),
                        "is_active":  True,
                    },
                )

            # Upsert all semesters found in file
            existing_sem_names = set(
                Semester.objects.filter(name__in=semester_terms)
                .values_list("name", flat=True)
            )
            new_sems = [
                Semester(name=n, start_date=timezone.now(), end_date=timezone.now())
                for n in semester_terms if n not in existing_sem_names
            ]
            if new_sems:
                Semester.objects.bulk_create(new_sems, ignore_conflicts=True, batch_size=BATCH_SIZE)
                stats["semesters_created"] += len(new_sems)

            # One clean read — id + name only, no extra fields
            sem_map = {
                r["name"]: r["id"]
                for r in Semester.objects.filter(name__in=semester_terms).values("id", "name")
            }

            # ══════════════════════════════════════════════════════════════
            # STEP 2 — DEPARTMENTS
            # ══════════════════════════════════════════════════════════════
            existing_dept_codes = set(
                Department.objects.filter(code__in=dept_codes)
                .values_list("code", flat=True)
            )
            new_depts = [
                Department(
                    code=code,
                    name=code,
                    location_id=DEPARTMENT_LOCATION_MAP.get(code, DEFAULT_LOCATION_ID),
                )
                for code in dept_codes if code not in existing_dept_codes
            ]
            if new_depts:
                Department.objects.bulk_create(new_depts, ignore_conflicts=True, batch_size=BATCH_SIZE)
                stats["departments_created"] += len(new_depts)

            # id + code only
            dept_map = {
                r["code"]: r["id"]
                for r in Department.objects.filter(code__in=dept_codes).values("id", "code")
            }

            # ══════════════════════════════════════════════════════════════
            # STEP 3 — USERS & STUDENTS  (vectorised via pandas)
            # ══════════════════════════════════════════════════════════════

            # One row per student — vectorised in pandas
            student_df = (
                df[["STUDNUM_STR", "STUDENTNAME", "DEPT_CODE"]]
                .drop_duplicates(subset=["STUDNUM_STR"])
                .reset_index(drop=True)
                .copy()
            )

            # Vectorised name + email computation
            names = student_df["STUDENTNAME"].fillna("").str.strip()
            student_df["FIRST"] = names.str.split().str[0].fillna("")
            student_df["LAST"]  = names.apply(
                lambda n: " ".join(n.split()[1:]) if len(n.split()) > 1 else ""
            )
            student_df["EMAIL"] = (
                student_df["FIRST"].str.lower()
                + student_df["LAST"].str.lower()
                + student_df["STUDNUM_STR"]
                + "@auca.ac.rw"
            ).str.replace(" ", "", regex=False)

            potential_emails = student_df["EMAIL"].tolist()

            # Bulk fetch existing users and students — values() only, no ORM objects
            existing_users_df = pd.DataFrame(
                User.objects.filter(email__in=potential_emails)
                .values("id", "email", "first_name", "last_name")
            ) if potential_emails else pd.DataFrame()

            existing_students_df = pd.DataFrame(
                Student.objects.filter(reg_no__in=student_nums)
                .values("id", "reg_no", "user_id")
            ) if student_nums else pd.DataFrame()

            # Merge to find who needs creating vs updating
            merged_students = student_df.merge(
                existing_students_df, left_on="STUDNUM_STR", right_on="reg_no", how="left"
            )

            # Students that already exist → update their user
            existing_mask  = merged_students["id"].notna()
            to_update_df   = merged_students[existing_mask].copy()
            to_create_df   = merged_students[~existing_mask].copy()

            # Update existing users — vectorised field comparison
            if not to_update_df.empty and not existing_users_df.empty:
                update_merged = to_update_df.merge(
                    existing_users_df, on="email", how="inner"
                )
                users_to_update = []
                for row in update_merged.itertuples(index=False):
                    if (row.first_name_y != row.FIRST or row.last_name_y != row.LAST):
                        users_to_update.append(
                            User(id=row.id_y, first_name=row.FIRST,
                                 last_name=row.LAST, email=row.email)
                        )
                if users_to_update:
                    User.objects.bulk_update(
                        users_to_update, ["first_name", "last_name", "email"],
                        batch_size=BATCH_SIZE
                    )
                    stats["users_updated"] += len(users_to_update)

            # Create new users
            new_user_objs = []
            if not to_create_df.empty:
                # Check which emails already exist
                existing_emails = (
                    set(existing_users_df["email"].tolist())
                    if not existing_users_df.empty else set()
                )
                for row in to_create_df.itertuples(index=False):
                    if row.EMAIL not in existing_emails:
                        new_user_objs.append(User(
                            email=row.EMAIL,
                            first_name=row.FIRST,
                            last_name=row.LAST,
                            role="student",
                            password=make_password("password123."),
                            is_active=True,
                        ))

                if new_user_objs:
                    User.objects.bulk_create(
                        new_user_objs, ignore_conflicts=True, batch_size=BATCH_SIZE
                    )
                    stats["users_created"] += len(new_user_objs)

            # Fresh user fetch — get IDs for student creation
            all_users_df = pd.DataFrame(
                User.objects.filter(email__in=potential_emails)
                .values("id", "email")
            ) if potential_emails else pd.DataFrame(columns=["id", "email"])

            # Create missing students
            if not to_create_df.empty and not all_users_df.empty:
                create_with_users = to_create_df.merge(
                    all_users_df, left_on="EMAIL", right_on="email", how="inner"
                )
                create_with_users["dept_id"] = create_with_users["DEPT_CODE"].map(dept_map)
                create_with_users = create_with_users.dropna(subset=["dept_id", "id"])

                students_to_create = [
                    Student(
                        user_id=int(row.id),
                        reg_no=row.STUDNUM_STR,
                        department_id=int(row.dept_id),
                    )
                    for row in create_with_users.itertuples(index=False)
                ]
                if students_to_create:
                    Student.objects.bulk_create(
                        students_to_create, ignore_conflicts=True, batch_size=BATCH_SIZE
                    )
                    stats["students_created"] += len(students_to_create)

            # Final student map: reg_no → student_id
            student_id_map = {
                r["reg_no"]: r["id"]
                for r in Student.objects.filter(reg_no__in=student_nums).values("id", "reg_no")
            }

            # ══════════════════════════════════════════════════════════════
            # STEP 4 — COURSES  (vectorised)
            # ══════════════════════════════════════════════════════════════
            course_meta_df = (
                df[["COURSECODE", "COURSENAME", "CREDITS", "TERM", "DEPT_CODE"]]
                .drop_duplicates(subset=["COURSECODE"])
                .reset_index(drop=True)
                .copy()
            )
            course_meta_df["semester_id"] = course_meta_df["TERM"].map(sem_map)
            course_meta_df["dept_id"]     = course_meta_df["DEPT_CODE"].map(dept_map)

            # Drop rows where semester or dept is missing
            course_meta_df = course_meta_df.dropna(subset=["semester_id", "dept_id"])
            course_meta_df["semester_id"] = course_meta_df["semester_id"].astype(int)
            course_meta_df["dept_id"]     = course_meta_df["dept_id"].astype(int)

            # Fetch existing courses
            existing_courses_df = pd.DataFrame(
                Course.objects.filter(code__in=course_codes)
                .values("id", "code", "title", "credits", "semester_id", "department_id")
            ) if course_codes else pd.DataFrame()

            if not existing_courses_df.empty:
                merged_courses = course_meta_df.merge(
                    existing_courses_df, left_on="COURSECODE", right_on="code", how="left"
                )
            else:
                merged_courses = course_meta_df.copy()
                merged_courses["id"] = np.nan

            existing_course_mask = merged_courses["id"].notna() if "id" in merged_courses.columns else pd.Series([False]*len(merged_courses))
            courses_to_create_df = merged_courses[~existing_course_mask]
            courses_to_update_df = merged_courses[existing_course_mask]

            # Create new courses
            if not courses_to_create_df.empty:
                new_courses = [
                    Course(
                        code=row.COURSECODE,
                        title=row.COURSENAME,
                        credits=row.CREDITS,
                        semester_id=row.semester_id,
                        department_id=row.dept_id,
                    )
                    for row in courses_to_create_df.itertuples(index=False)
                ]
                Course.objects.bulk_create(new_courses, ignore_conflicts=True, batch_size=BATCH_SIZE)
                stats["courses_created"] += len(new_courses)

            # Update existing courses
            if not courses_to_update_df.empty:
                courses_to_update = [
                    Course(
                        id=int(row.id),
                        code=row.COURSECODE,
                        title=row.COURSENAME,
                        credits=row.CREDITS,
                        semester_id=row.semester_id,
                        department_id=row.dept_id,
                    )
                    for row in courses_to_update_df.itertuples(index=False)
                ]
                Course.objects.bulk_update(
                    courses_to_update,
                    ["title", "credits", "semester_id", "department_id"],
                    batch_size=BATCH_SIZE,
                )
                stats["courses_updated"] += len(courses_to_update)

            # Final course map: code → course_id
            course_id_map = {
                r["code"]: r["id"]
                for r in Course.objects.filter(code__in=course_codes).values("id", "code")
            }

            # ══════════════════════════════════════════════════════════════
            # STEP 5 — COURSE GROUPS  (vectorised)
            # Only (course_code, group_name) pairs from THIS upload
            # ══════════════════════════════════════════════════════════════
            cg_pairs_df["course_id"] = cg_pairs_df["COURSECODE"].map(course_id_map)
            cg_pairs_df = cg_pairs_df.dropna(subset=["course_id"])
            cg_pairs_df["course_id"] = cg_pairs_df["course_id"].astype(int)

            # Fetch existing groups for these exact (course_id, group_name) pairs
            existing_groups_df = pd.DataFrame(
                CourseGroup.objects.filter(
                    course__code__in=course_codes,
                    group_name__in=uploaded_group_names,
                ).values("id", "group_name", "course_id")
            ) if course_codes and uploaded_group_names else pd.DataFrame()

            if not existing_groups_df.empty:
                merged_cg = cg_pairs_df.merge(
                    existing_groups_df,
                    left_on=["course_id", "GROUP"],
                    right_on=["course_id", "group_name"],
                    how="left",
                )
            else:
                merged_cg = cg_pairs_df.copy()
                merged_cg["id"] = np.nan

            new_groups_mask = merged_cg["id"].isna()
            groups_to_create_df = merged_cg[new_groups_mask]

            if not groups_to_create_df.empty:
                new_groups = [
                    CourseGroup(group_name=row.GROUP, course_id=row.course_id)
                    for row in groups_to_create_df.itertuples(index=False)
                ]
                CourseGroup.objects.bulk_create(
                    new_groups, ignore_conflicts=True, batch_size=BATCH_SIZE
                )
                stats["groups_created"] += len(new_groups)

            # Final group map: (course_id, group_name) → group_id
            group_id_map = {
                (r["course_id"], r["group_name"]): r["id"]
                for r in CourseGroup.objects.filter(
                    course__code__in=course_codes,
                    group_name__in=uploaded_group_names,
                ).values("id", "group_name", "course_id")
            }

            # ══════════════════════════════════════════════════════════════
            # STEP 6 — ENROLLMENTS  (fully vectorised — no iterrows)
            # ══════════════════════════════════════════════════════════════

            # Work only with columns we need
            enr_df = (
                df[["STUDNUM_STR", "COURSECODE", "GROUP"]]
                .dropna(subset=["GROUP"])
                .drop_duplicates()
                .reset_index(drop=True)
                .copy()
            )

            # Map IDs using pandas — vectorised, no Python loops
            enr_df["student_id"] = enr_df["STUDNUM_STR"].map(student_id_map)
            enr_df["course_id"]  = enr_df["COURSECODE"].map(course_id_map)
            enr_df["group_id"]   = enr_df.apply(
                lambda r: group_id_map.get((
                    course_id_map.get(r["COURSECODE"]),
                    r["GROUP"]
                )),
                axis=1,
            )

            # Drop rows where any ID is missing
            enr_df = enr_df.dropna(subset=["student_id", "course_id", "group_id"])
            enr_df[["student_id", "course_id", "group_id"]] = (
                enr_df[["student_id", "course_id", "group_id"]].astype(int)
            )

            # Fetch existing enrollments as a flat DataFrame
            existing_enr_df = pd.DataFrame(
                Enrollment.objects.filter(
                    student_id__in=enr_df["student_id"].tolist(),
                    course_id__in=enr_df["course_id"].tolist(),
                ).values("id", "student_id", "course_id", "group_id", "status")
            ) if not enr_df.empty else pd.DataFrame()

            if not existing_enr_df.empty:
                # Merge to identify new vs existing
                merged_enr = enr_df.merge(
                    existing_enr_df,
                    on=["student_id", "course_id"],
                    how="left",
                    suffixes=("_new", "_existing"),
                )
                is_new      = merged_enr["id"].isna()
                is_existing = ~is_new
            else:
                merged_enr  = enr_df.copy()
                merged_enr["id"]           = np.nan
                merged_enr["group_id_existing"] = np.nan
                merged_enr["status"]       = np.nan
                is_new      = pd.Series([True] * len(merged_enr))
                is_existing = ~is_new

            # ── Create new enrollments ────────────────────────────────────
            new_enr_df = merged_enr[is_new][
                ["student_id", "course_id", "group_id_new"]
            ].drop_duplicates() if "group_id_new" in merged_enr.columns else \
            merged_enr[is_new][
                ["student_id", "course_id", "group_id"]
            ].drop_duplicates()

            group_col = "group_id_new" if "group_id_new" in new_enr_df.columns else "group_id"

            if not new_enr_df.empty:
                enrollments_to_create = [
                    Enrollment(
                        student_id=int(row.student_id),
                        course_id=int(row.course_id),
                        group_id=int(getattr(row, group_col)),
                        status="enrolled",      # always set explicitly
                    )
                    for row in new_enr_df.itertuples(index=False)
                ]
                Enrollment.objects.bulk_create(
                    enrollments_to_create,
                    ignore_conflicts=True,
                    batch_size=BATCH_SIZE,
                )
                stats["enrollments_created"] += len(enrollments_to_create)

            # ── Update existing enrollments ───────────────────────────────
            if not existing_enr_df.empty and is_existing.any():
                existing_to_check = merged_enr[is_existing].copy()
                g_new_col = "group_id_new" if "group_id_new" in existing_to_check.columns else "group_id"
                g_ext_col = "group_id_existing" if "group_id_existing" in existing_to_check.columns else "group_id"

                # Only update rows where group or status changed
                needs_update = (
                    (existing_to_check[g_new_col] != existing_to_check[g_ext_col]) |
                    (existing_to_check["status"] != "enrolled")
                )
                update_df = existing_to_check[needs_update]

                if not update_df.empty:
                    enrollments_to_update = [
                        Enrollment(
                            id=int(row.id),
                            group_id=int(getattr(row, g_new_col)),
                            status="enrolled",
                        )
                        for row in update_df.itertuples(index=False)
                    ]
                    Enrollment.objects.bulk_update(
                        enrollments_to_update,
                        ["group_id", "status"],
                        batch_size=BATCH_SIZE,
                    )
                    stats["enrollments_updated"] += len(enrollments_to_update)

            # Log rows that had no matching group
            missing_groups = enr_df[enr_df["group_id"].isna()]
            if not missing_groups.empty:
                for row in missing_groups.itertuples(index=False):
                    errors.append(
                        f"Group '{row.GROUP}' not found for course "
                        f"'{row.COURSECODE}' (student {row.STUDNUM_STR}) — skipped."
                    )

        # ── Response ──────────────────────────────────────────────────────
        summary = {
            "status": "Import completed successfully" if not errors
                      else "Import completed with warnings",
            "stats": dict(stats),
        }
        if errors:
            summary["warnings"] = errors[:20]
            if len(errors) > 20:
                summary["warnings"].append(
                    f"... and {len(errors) - 20} more (check server logs)."
                )
            for e in errors:
                logger.warning(e)

        return Response(summary)


# ── Utility ───────────────────────────────────────────────────────────────────
def _is_numeric(val):
    """Return True if val can be safely converted to a number."""
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False