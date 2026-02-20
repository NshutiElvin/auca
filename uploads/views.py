"""
ImportEnrollmentsData — SSE Streaming Version
==============================================
- HTTP request returns immediately with a stream
- Frontend receives real-time progress updates via SSE
- No timeout — connection stays alive with periodic progress events
- React can display live progress bar/log while import runs
"""

from departments.models import Department
from rest_framework import generics, parsers
from rest_framework.response import Response
from django.http import StreamingHttpResponse
import pandas as pd
import numpy as np
import json
import io
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
BATCH_SIZE = 1000


# ── Helpers ───────────────────────────────────────────────────────────────────
def _is_numeric(val):
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False


def _dept_code_str(raw):
    if _is_numeric(raw) and not pd.isna(raw):
        return str(int(float(raw)))
    return str(raw)


def _safe_df(queryset, columns):
    """
    Always returns DataFrame with correct columns
    even when queryset is empty — prevents KeyError on merge.
    """
    rows = list(queryset)
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=columns)


def _sse_event(event_type, data):
    """
    Format a single SSE event string.
    Frontend receives: { type, ...data }
    """
    payload = json.dumps({"type": event_type, **data})
    return f"data: {payload}\n\n"


def _progress(step, total_steps, message, stats=None):
    """Build a progress SSE event."""
    event = {
        "step":        step,
        "total_steps": total_steps,
        "percent":     round((step / total_steps) * 100),
        "message":     message,
    }
    if stats:
        event["stats"] = stats
    return _sse_event("progress", event)


def _done(stats, warnings):
    """Build the final done SSE event."""
    return _sse_event("done", {
        "message":  "Import completed successfully" if not warnings
                    else "Import completed with warnings",
        "stats":    stats,
        "warnings": warnings[:20],
    })


def _error(message):
    """Build an error SSE event."""
    return _sse_event("error", {"message": message})


# ── Main View ─────────────────────────────────────────────────────────────────
class ImportEnrollmentsData(generics.GenericAPIView):
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, *args, **kwargs):
        file              = request.FILES.get("myFile")
        selected_semester = request.data.get("selectedSemester")

        if not file:
            return Response({"error": "No file provided."}, status=400)

        # Read file into memory immediately — before stream starts
        # (file object will be gone once we start streaming)
        file_bytes        = file.read()
        selected_semester = selected_semester

        def event_stream():
            """
            Generator that yields SSE events.
            Django keeps the HTTP connection open as long as
            this generator is running.
            """
            TOTAL_STEPS = 8

            try:
                # ── Step 1: Read & validate ───────────────────────────────
                yield _progress(1, TOTAL_STEPS, "Reading and validating file...")

                try:
                    df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
                except Exception as exc:
                    yield _error(f"Could not read file: {exc}")
                    return

                required = {"COURSECODE", "COURSENAME", "CREDITS", "GROUP",
                            "STUDNUM", "STUDENTNAME", "FACULTYCODE", "TERM"}
                missing = required - set(df.columns)
                if missing:
                    yield _error(f"Missing columns: {missing}")
                    return

                df = df.dropna(subset=["STUDNUM"])
                df["STUDNUM_STR"] = df["STUDNUM"].str.strip().apply(
                    lambda x: str(int(float(x))) if _is_numeric(x) else None
                )
                df = df.dropna(subset=["STUDNUM_STR"])

                if df.empty:
                    yield _error("No valid student records found in file.")
                    return

                df["DEPT_CODE"] = df["FACULTYCODE"].apply(
                    lambda x: str(int(float(x))) if _is_numeric(x) else str(x)
                )

                # Unique sets
                student_nums         = df["STUDNUM_STR"].dropna().unique().tolist()
                dept_codes           = df["DEPT_CODE"].dropna().unique().tolist()
                course_codes         = df["COURSECODE"].dropna().unique().tolist()
                semester_terms       = df["TERM"].dropna().unique().tolist()
                uploaded_group_names = df["GROUP"].dropna().unique().tolist()

                cg_pairs_df = (
                    df[["COURSECODE", "GROUP"]]
                    .dropna(subset=["GROUP"])
                    .drop_duplicates()
                    .reset_index(drop=True)
                    .copy()
                )

                stats  = defaultdict(int)
                errors = []

                yield _progress(1, TOTAL_STEPS,
                    f"File valid — {len(student_nums):,} students, "
                    f"{len(course_codes):,} courses, "
                    f"{len(df):,} enrollment rows")

                with transaction.atomic():

                    # ── Step 2: Semesters & Departments ──────────────────
                    yield _progress(2, TOTAL_STEPS, "Processing semesters and departments...")

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

                    existing_sem_names = set(
                        Semester.objects.filter(name__in=semester_terms)
                        .values_list("name", flat=True)
                    )
                    new_sems = [
                        Semester(name=n, start_date=timezone.now(), end_date=timezone.now())
                        for n in semester_terms if n not in existing_sem_names
                    ]
                    if new_sems:
                        Semester.objects.bulk_create(
                            new_sems, ignore_conflicts=True, batch_size=BATCH_SIZE
                        )
                        stats["semesters_created"] += len(new_sems)

                    sem_map = {
                        r["name"]: r["id"]
                        for r in Semester.objects.filter(
                            name__in=semester_terms
                        ).values("id", "name")
                    }

                    existing_dept_codes = set(
                        Department.objects.filter(code__in=dept_codes)
                        .values_list("code", flat=True)
                    )
                    new_depts = [
                        Department(
                            code=code, name=code,
                            location_id=DEPARTMENT_LOCATION_MAP.get(code, DEFAULT_LOCATION_ID),
                        )
                        for code in dept_codes if code not in existing_dept_codes
                    ]
                    if new_depts:
                        Department.objects.bulk_create(
                            new_depts, ignore_conflicts=True, batch_size=BATCH_SIZE
                        )
                        stats["departments_created"] += len(new_depts)

                    dept_map = {
                        r["code"]: r["id"]
                        for r in Department.objects.filter(
                            code__in=dept_codes
                        ).values("id", "code")
                    }

                    # ── Step 3: Users & Students ──────────────────────────
                    yield _progress(3, TOTAL_STEPS,
                        f"Processing {len(student_nums):,} students...")

                    student_df = (
                        df[["STUDNUM_STR", "STUDENTNAME", "DEPT_CODE"]]
                        .drop_duplicates(subset=["STUDNUM_STR"])
                        .reset_index(drop=True)
                        .copy()
                    )

                    names = student_df["STUDENTNAME"].fillna("").astype(str).str.strip()
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

                    potential_emails = student_df["EMAIL"].dropna().tolist()

                    existing_users_df = _safe_df(
                        User.objects.filter(email__in=potential_emails)
                        .values("id", "email", "first_name", "last_name"),
                        columns=["id", "email", "first_name", "last_name"]
                    )
                    existing_students_df = _safe_df(
                        Student.objects.filter(reg_no__in=student_nums)
                        .values("id", "reg_no", "user_id"),
                        columns=["id", "reg_no", "user_id"]
                    )

                    merged_students = student_df.merge(
                        existing_students_df[["id", "reg_no"]],
                        left_on="STUDNUM_STR", right_on="reg_no", how="left",
                    )

                    existing_mask = merged_students["id"].notna()
                    to_update_df  = merged_students[existing_mask].copy()
                    to_create_df  = merged_students[~existing_mask].copy()

                    # Update existing users
                    if not to_update_df.empty and not existing_users_df.empty:
                        update_merged = to_update_df.merge(
                            existing_users_df[["id", "email", "first_name", "last_name"]],
                            left_on="EMAIL", right_on="email", how="inner", # <--- Fixed KeyError bug here
                            suffixes=("_student", "_user"),
                        )
                        users_to_update = []
                        for row in update_merged.itertuples(index=False):
                            fn  = getattr(row, "first_name_user", None)
                            ln  = getattr(row, "last_name_user", None)
                            uid = getattr(row, "id_user", None)
                            if fn != row.FIRST or ln != row.LAST:
                                users_to_update.append(
                                    User(id=int(uid), first_name=row.FIRST,
                                         last_name=row.LAST, email=row.email)
                                )
                        if users_to_update:
                            User.objects.bulk_update(
                                users_to_update,
                                ["first_name", "last_name", "email"],
                                batch_size=BATCH_SIZE,
                            )
                            stats["users_updated"] += len(users_to_update)

                    # Create new users
                    existing_emails = (
                        set(existing_users_df["email"].tolist())
                        if not existing_users_df.empty else set()
                    )
                    new_user_objs = []
                    if not to_create_df.empty:
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

                    # Fresh fetch for IDs
                    all_users_df = _safe_df(
                        User.objects.filter(email__in=potential_emails)
                        .values("id", "email"),
                        columns=["id", "email"]
                    )

                    if not to_create_df.empty and not all_users_df.empty:
                        create_with_users = to_create_df.merge(
                            all_users_df, left_on="EMAIL", right_on="email",
                            how="inner", suffixes=("", "_user"),
                        )
                        create_with_users["dept_id"] = (
                            create_with_users["DEPT_CODE"].map(dept_map)
                        )
                        create_with_users = create_with_users.dropna(subset=["dept_id"])
                        students_to_create = [
                            Student(
                                user_id=int(row.id_user),  # <--- Fixed NaN issue here
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

                    student_id_map = {
                        r["reg_no"]: r["id"]
                        for r in Student.objects.filter(
                            reg_no__in=student_nums
                        ).values("id", "reg_no")
                    }

                    yield _progress(3, TOTAL_STEPS,
                        f"Students done — "
                        f"{stats['students_created']:,} created, "
                        f"{stats['users_updated']:,} updated",
                        stats=dict(stats))

                    # ── Step 4: Courses ───────────────────────────────────
                    yield _progress(4, TOTAL_STEPS,
                        f"Processing {len(course_codes):,} courses...")

                    course_meta_df = (
                        df[["COURSECODE", "COURSENAME", "CREDITS", "TERM", "DEPT_CODE"]]
                        .drop_duplicates(subset=["COURSECODE"])
                        .reset_index(drop=True)
                        .copy()
                    )
                    course_meta_df["semester_id"] = course_meta_df["TERM"].map(sem_map)
                    course_meta_df["dept_id"]     = course_meta_df["DEPT_CODE"].map(dept_map)
                    course_meta_df = course_meta_df.dropna(subset=["semester_id", "dept_id"])
                    course_meta_df["semester_id"] = course_meta_df["semester_id"].astype(int)
                    course_meta_df["dept_id"]     = course_meta_df["dept_id"].astype(int)

                    existing_courses_df = _safe_df(
                        Course.objects.filter(code__in=course_codes)
                        .values("id", "code", "title", "credits",
                                "semester_id", "department_id"),
                        columns=["id", "code", "title", "credits",
                                 "semester_id", "department_id"]
                    )

                    merged_courses = course_meta_df.merge(
                        existing_courses_df[["id", "code"]],
                        left_on="COURSECODE", right_on="code", how="left",
                    )

                    new_mask_c = merged_courses["id"].isna()
                    if not merged_courses[new_mask_c].empty:
                        Course.objects.bulk_create([
                            Course(
                                code=row.COURSECODE, title=row.COURSENAME,
                                credits=row.CREDITS, semester_id=row.semester_id,
                                department_id=row.dept_id,
                            )
                            for row in merged_courses[new_mask_c].itertuples(index=False)
                        ], ignore_conflicts=True, batch_size=BATCH_SIZE)
                        stats["courses_created"] += int(new_mask_c.sum())

                    if not merged_courses[~new_mask_c].empty:
                        Course.objects.bulk_update([
                            Course(
                                id=int(row.id), title=row.COURSENAME,
                                credits=row.CREDITS, semester_id=row.semester_id,
                                department_id=row.dept_id,
                            )
                            for row in merged_courses[~new_mask_c].itertuples(index=False)
                        ], ["title", "credits", "semester_id", "department_id"],
                        batch_size=BATCH_SIZE)
                        stats["courses_updated"] += int((~new_mask_c).sum())

                    course_id_map = {
                        r["code"]: r["id"]
                        for r in Course.objects.filter(
                            code__in=course_codes
                        ).values("id", "code")
                    }

                    # ── Step 5: Course Groups ─────────────────────────────
                    yield _progress(5, TOTAL_STEPS, "Processing course groups...")

                    cg_pairs_df["course_id"] = cg_pairs_df["COURSECODE"].map(course_id_map)
                    cg_pairs_df = cg_pairs_df.dropna(subset=["course_id"]).copy()
                    cg_pairs_df["course_id"] = cg_pairs_df["course_id"].astype(int)

                    existing_groups_df = _safe_df(
                        CourseGroup.objects.filter(
                            course__code__in=course_codes,
                            group_name__in=uploaded_group_names,
                        ).values("id", "group_name", "course_id"),
                        columns=["id", "group_name", "course_id"]
                    )

                    merged_cg = cg_pairs_df.merge(
                        existing_groups_df[["id", "group_name", "course_id"]],
                        left_on=["course_id", "GROUP"],
                        right_on=["course_id", "group_name"],
                        how="left",
                    )

                    new_groups_df = merged_cg[merged_cg["id"].isna()]
                    if not new_groups_df.empty:
                        CourseGroup.objects.bulk_create([
                            CourseGroup(
                                group_name=row.GROUP, course_id=int(row.course_id)
                            )
                            for row in new_groups_df.itertuples(index=False)
                        ], ignore_conflicts=True, batch_size=BATCH_SIZE)
                        stats["groups_created"] += len(new_groups_df)

                    group_id_map = {
                        (r["course_id"], r["group_name"]): r["id"]
                        for r in CourseGroup.objects.filter(
                            course__code__in=course_codes,
                            group_name__in=uploaded_group_names,
                        ).values("id", "group_name", "course_id")
                    }

                    # ── Step 6: Enrollments ───────────────────────────────
                    yield _progress(6, TOTAL_STEPS,
                        f"Processing {len(df):,} enrollment rows...")

                    enr_df = (
                        df[["STUDNUM_STR", "COURSECODE", "GROUP"]]
                        .dropna(subset=["GROUP"])
                        .drop_duplicates()
                        .reset_index(drop=True)
                        .copy()
                    )

                    enr_df["student_id"] = enr_df["STUDNUM_STR"].map(student_id_map)
                    enr_df["course_id"]  = enr_df["COURSECODE"].map(course_id_map)
                    enr_df["group_id"]   = enr_df.apply(
                        lambda r: group_id_map.get(
                            (course_id_map.get(r["COURSECODE"]), r["GROUP"])
                        ),
                        axis=1,
                    )

                    # Log missing groups
                    for row in enr_df[enr_df["group_id"].isna()].itertuples(index=False):
                        errors.append(
                            f"Group '{row.GROUP}' not found for course "
                            f"'{row.COURSECODE}' (student {row.STUDNUM_STR}) — skipped."
                        )

                    enr_df = enr_df.dropna(subset=["student_id", "course_id", "group_id"])

                    if enr_df.empty:
                        errors.append("No enrollments could be resolved.")
                    else:
                        enr_df[["student_id", "course_id", "group_id"]] = (
                            enr_df[["student_id", "course_id", "group_id"]].astype(int)
                        )

                        existing_enr_df = _safe_df(
                            Enrollment.objects.filter(
                                student_id__in=enr_df["student_id"].tolist(),
                                course_id__in=enr_df["course_id"].tolist(),
                            ).values("id", "student_id", "course_id", "group_id", "status"),
                            columns=["id", "student_id", "course_id", "group_id", "status"]
                        )

                        merged_enr = enr_df.merge(
                            existing_enr_df[["id", "student_id", "course_id",
                                             "group_id", "status"]],
                            on=["student_id", "course_id"],
                            how="left",
                            suffixes=("_new", "_existing"),
                        )

                        is_new      = merged_enr["id"].isna()
                        is_existing = ~is_new

                        # Create new
                        new_enr_df = merged_enr[is_new].copy()
                        g_col      = "group_id_new" if "group_id_new" in new_enr_df.columns \
                                     else "group_id"
                        if not new_enr_df.empty:
                            Enrollment.objects.bulk_create([
                                Enrollment(
                                    student_id=int(row.student_id),
                                    course_id=int(row.course_id),
                                    group_id=int(getattr(row, g_col)),
                                    status="enrolled",
                                )
                                for row in new_enr_df.itertuples(index=False)
                            ], ignore_conflicts=True, batch_size=BATCH_SIZE)
                            stats["enrollments_created"] += len(new_enr_df)

                        # Update changed
                        if is_existing.any():
                            ext_rows  = merged_enr[is_existing].copy()
                            g_new_col = "group_id_new" if "group_id_new" in ext_rows.columns \
                                        else "group_id"
                            g_ext_col = "group_id_existing" if "group_id_existing" in ext_rows.columns \
                                        else "group_id"
                            needs_update = (
                                (ext_rows[g_new_col] != ext_rows[g_ext_col]) |
                                (ext_rows["status"] != "enrolled")
                            )
                            update_df = ext_rows[needs_update]
                            if not update_df.empty:
                                Enrollment.objects.bulk_update([
                                    Enrollment(
                                        id=int(row.id),
                                        group_id=int(getattr(row, g_new_col)),
                                        status="enrolled",
                                    )
                                    for row in update_df.itertuples(index=False)
                                ], ["group_id", "status"], batch_size=BATCH_SIZE)
                                stats["enrollments_updated"] += len(update_df)

                    yield _progress(6, TOTAL_STEPS,
                        f"Enrollments done — "
                        f"{stats['enrollments_created']:,} created, "
                        f"{stats['enrollments_updated']:,} updated",
                        stats=dict(stats))

                # ── Step 7: Complete ──────────────────────────────────────
                yield _progress(8, TOTAL_STEPS, "Finalising...", stats=dict(stats))
                yield _done(dict(stats), errors)

            except Exception as exc:
                logger.error(f"Import failed: {exc}", exc_info=True)
                yield _error(f"Import failed: {str(exc)}")

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"]              = "no-cache"
        response["X-Accel-Buffering"]          = "no"   # disable nginx buffering
        response["Access-Control-Allow-Origin"]  = "*"
        return response