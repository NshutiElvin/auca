"""
ImportEnrollmentsData — Optimized Async SSE Streaming Version v2
================================================================
Optimizations:
 1. make_password called ONCE (was: bcrypt × 30k users)
 2. course_dept_mapping built with groupby, not iterrows loop
 3. update_or_create loop replaced with bulk_create + bulk_update for courses
 4. associated_departments.set() batched via through-model bulk_create
 5. Enrollment existence check uses course_id__in (232 values) not student_id__in (22k values)
 6. All heavy sections chunked with live progress callbacks
 7. DataFrame operations vectorized wherever possible
 8. Enrollment deduplication before bulk_create
"""

from departments.models import Department
from rest_framework import generics, parsers
from rest_framework.response import Response
from django.http import StreamingHttpResponse
from asgiref.sync import sync_to_async
import pandas as pd
import asyncio
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

# ── Configuration ──────────────────────────────────────────────────────────────
DEPARTMENT_LOCATION_MAP = {
    "15": 1,
    "12": 1,
    "19": 1,
}
DEFAULT_LOCATION_ID = 2
BATCH_SIZE = 1000


# ── Helpers ────────────────────────────────────────────────────────────────────
def _is_numeric(val):
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False


def _safe_df(queryset, columns):
    rows = list(queryset)
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=columns)


def _sse_event(event_type, data):
    payload = json.dumps({"type": event_type, **data})
    return f"data: {payload}\n\n"


def _progress(step, total_steps, message, stats=None):
    event = {
        "step": step,
        "total_steps": total_steps,
        "percent": round((step / total_steps) * 100),
        "message": message,
    }
    if stats:
        event["stats"] = stats
    return _sse_event("progress", event)


def _done(stats, warnings):
    return _sse_event(
        "done",
        {
            "message": (
                "Import completed successfully"
                if not warnings
                else "Import completed with warnings"
            ),
            "stats": stats,
            "warnings": warnings[:20],
        },
    )


def _error(message):
    return _sse_event("error", {"message": message})


# ── Sync Import Logic ──────────────────────────────────────────────────────────
def _run_import(file_bytes, selected_semester, progress_callback):
    TOTAL_STEPS = 8
    stats = defaultdict(int)
    errors = []

    # ── Step 1: Read & validate ────────────────────────────────────────────────
    progress_callback(1, TOTAL_STEPS, "Reading and validating file...")

    try:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not read file: {exc}")

    required = {
        "COURSECODE", "COURSENAME", "CREDITS", "GROUP",
        "STUDNUM", "STUDENTNAME", "FACULTYCODE", "TERM",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df = df.dropna(subset=["STUDNUM"])
    df["STUDNUM_STR"] = (
        df["STUDNUM"]
        .str.strip()
        .apply(lambda x: str(int(float(x))) if _is_numeric(x) else None)
    )
    df = df.dropna(subset=["STUDNUM_STR"])

    if df.empty:
        raise ValueError("No valid student records found in file.")

    df["DEPT_CODE"] = df["FACULTYCODE"].apply(
        lambda x: str(int(float(x))) if _is_numeric(x) else str(x)
    )

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

    progress_callback(
        1, TOTAL_STEPS,
        f"File valid — {len(student_nums):,} students, "
        f"{len(course_codes):,} courses, "
        f"{len(df):,} enrollment rows",
    )

    with transaction.atomic():

        # ── Step 2: Semesters & Departments ───────────────────────────────────
        progress_callback(2, TOTAL_STEPS, "Processing semesters and departments...")

        if selected_semester:
            Semester.objects.exclude(name=selected_semester).update(is_active=False)
            Semester.objects.update_or_create(
                name=selected_semester,
                defaults={
                    "start_date": timezone.now(),
                    "end_date": timezone.now(),
                    "is_active": True,
                },
            )

        existing_sem_names = set(
            Semester.objects.filter(name__in=semester_terms).values_list("name", flat=True)
        )
        new_sems = [
            Semester(name=n, start_date=timezone.now(), end_date=timezone.now())
            for n in semester_terms
            if n not in existing_sem_names
        ]
        if new_sems:
            Semester.objects.bulk_create(new_sems, ignore_conflicts=True, batch_size=BATCH_SIZE)
            stats["semesters_created"] += len(new_sems)

        sem_map = {
            r["name"]: r["id"]
            for r in Semester.objects.filter(name__in=semester_terms).values("id", "name")
        }

        existing_dept_codes = set(
            Department.objects.filter(code__in=dept_codes).values_list("code", flat=True)
        )
        new_depts = [
            Department(
                code=code,
                name=code,
                location_id=DEPARTMENT_LOCATION_MAP.get(code, DEFAULT_LOCATION_ID),
            )
            for code in dept_codes
            if code not in existing_dept_codes
        ]
        if new_depts:
            Department.objects.bulk_create(new_depts, ignore_conflicts=True, batch_size=BATCH_SIZE)
            stats["departments_created"] += len(new_depts)

        dept_map = {
            r["code"]: r["id"]
            for r in Department.objects.filter(code__in=dept_codes).values("id", "code")
        }

        # ── Step 3: Users & Students ───────────────────────────────────────────
        progress_callback(3, TOTAL_STEPS, f"Processing {len(student_nums):,} students...")

        student_df = (
            df[["STUDNUM_STR", "STUDENTNAME", "DEPT_CODE"]]
            .drop_duplicates(subset=["STUDNUM_STR"])
            .reset_index(drop=True)
            .copy()
        )

        names = student_df["STUDENTNAME"].fillna("").astype(str).str.strip()
        split_names = names.str.split()
        student_df["FIRST"] = split_names.str[0].fillna("")
        student_df["LAST"]  = split_names.apply(
            lambda parts: " ".join(parts[1:]) if parts and len(parts) > 1 else ""
        )
        # Vectorized email construction
        student_df["EMAIL"] = (
            student_df["FIRST"].str.lower().str.replace(" ", "", regex=False)
            + student_df["LAST"].str.lower().str.replace(" ", "", regex=False)
            + student_df["STUDNUM_STR"]
            + "@auca.ac.rw"
        )

        potential_emails = student_df["EMAIL"].dropna().tolist()

        existing_students_df = _safe_df(
            Student.objects.filter(reg_no__in=student_nums).values("id", "reg_no", "user_id"),
            columns=["id", "reg_no", "user_id"],
        )

        # Set-difference split — faster than merge+mask
        existing_reg_nos = (
            set(existing_students_df["reg_no"].tolist())
            if not existing_students_df.empty
            else set()
        )
        to_create_df = student_df[~student_df["STUDNUM_STR"].isin(existing_reg_nos)].copy()
        to_update_df = student_df[student_df["STUDNUM_STR"].isin(existing_reg_nos)].copy()

        # Update existing users (only when name actually changed)
        if not to_update_df.empty:
            existing_users_df = _safe_df(
                User.objects.filter(email__in=to_update_df["EMAIL"].tolist()).values(
                    "id", "email", "first_name", "last_name"
                ),
                columns=["id", "email", "first_name", "last_name"],
            )
            if not existing_users_df.empty:
                update_merged = to_update_df.merge(
                    existing_users_df,
                    left_on="EMAIL",
                    right_on="email",
                    how="inner",
                    suffixes=("_new", "_existing"),
                )
                needs_name_update = (
                    (update_merged["FIRST"] != update_merged["first_name"])
                    | (update_merged["LAST"]  != update_merged["last_name"])
                )
                update_rows = update_merged[needs_name_update]
                if not update_rows.empty:
                    users_to_update = [
                        User(id=int(row.id), first_name=row.FIRST, last_name=row.LAST, email=row.email)
                        for row in update_rows.itertuples(index=False)
                    ]
                    User.objects.bulk_update(
                        users_to_update, ["first_name", "last_name", "email"], batch_size=BATCH_SIZE
                    )
                    stats["users_updated"] += len(users_to_update)

        # Create new users — hash password ONCE (was: make_password() per user = bcrypt × N)
        if not to_create_df.empty:
            existing_emails_set = set(
                User.objects.filter(email__in=to_create_df["EMAIL"].tolist())
                .values_list("email", flat=True)
            )
            hashed_password = make_password("password123.")  # single bcrypt call

            new_user_objs = [
                User(
                    email=row.EMAIL,
                    first_name=row.FIRST,
                    last_name=row.LAST,
                    role="student",
                    password=hashed_password,
                    is_active=True,
                )
                for row in to_create_df.itertuples(index=False)
                if row.EMAIL not in existing_emails_set
            ]

            total_new = len(new_user_objs)
            for i in range(0, total_new, BATCH_SIZE):
                User.objects.bulk_create(new_user_objs[i : i + BATCH_SIZE], ignore_conflicts=True)
                progress_callback(
                    3, TOTAL_STEPS,
                    f"Creating users... {min(i + BATCH_SIZE, total_new):,}/{total_new:,}",
                )
            stats["users_created"] += total_new

        # Fresh fetch for user IDs
        all_users_df = _safe_df(
            User.objects.filter(email__in=potential_emails).values("id", "email"),
            columns=["id", "email"],
        )

        if not to_create_df.empty and not all_users_df.empty:
            create_with_users = to_create_df.merge(
                all_users_df,
                left_on="EMAIL",
                right_on="email",
                how="inner",
            )
            create_with_users["dept_id"] = create_with_users["DEPT_CODE"].map(dept_map)
            create_with_users = create_with_users.dropna(subset=["dept_id"])

            students_to_create = [
                Student(
                    user_id=int(row.id),
                    reg_no=row.STUDNUM_STR,
                    department_id=int(row.dept_id),
                )
                for row in create_with_users.itertuples(index=False)
            ]
            total_students = len(students_to_create)
            for i in range(0, total_students, BATCH_SIZE):
                Student.objects.bulk_create(
                    students_to_create[i : i + BATCH_SIZE], ignore_conflicts=True
                )
                progress_callback(
                    3, TOTAL_STEPS,
                    f"Creating students... {min(i + BATCH_SIZE, total_students):,}/{total_students:,}",
                )
            stats["students_created"] += total_students

        student_id_map = {
            r["reg_no"]: r["id"]
            for r in Student.objects.filter(reg_no__in=student_nums).values("id", "reg_no")
        }

        progress_callback(
            3, TOTAL_STEPS,
            f"Students done — "
            f"{stats['students_created']:,} created, "
            f"{stats['users_updated']:,} updated",
            stats=dict(stats),
        )

        # ── Step 4: Courses ────────────────────────────────────────────────────
        progress_callback(4, TOTAL_STEPS, f"Processing {len(course_codes):,} courses...")

        # groupby instead of iterrows loop
        course_dept_mapping = (
            df.dropna(subset=["COURSECODE", "DEPT_CODE"])
            .groupby("COURSECODE")["DEPT_CODE"]
            .apply(set)
            .to_dict()
        )

        # Primary dept = dept with highest enrollment count per course
        course_dept_counts = (
            df.dropna(subset=["COURSECODE", "DEPT_CODE"])
            .groupby(["COURSECODE", "DEPT_CODE"])
            .size()
            .reset_index(name="cnt")
        )
        primary_dept_series = (
            course_dept_counts
            .sort_values("cnt", ascending=False)
            .drop_duplicates(subset=["COURSECODE"])
            .set_index("COURSECODE")["DEPT_CODE"]
        )

        course_meta_df = (
            df[["COURSECODE", "COURSENAME", "CREDITS", "TERM"]]
            .drop_duplicates(subset=["COURSECODE"])
            .reset_index(drop=True)
            .copy()
        )
        course_meta_df["semester_id"]     = course_meta_df["TERM"].map(sem_map)
        course_meta_df = course_meta_df.dropna(subset=["semester_id"]).copy()
        course_meta_df["semester_id"]     = course_meta_df["semester_id"].astype(int)
        course_meta_df["primary_dept"]    = course_meta_df["COURSECODE"].map(primary_dept_series)
        course_meta_df["primary_dept_id"] = course_meta_df["primary_dept"].map(dept_map)
        course_meta_df = course_meta_df.dropna(subset=["primary_dept_id"]).copy()
        course_meta_df["primary_dept_id"] = course_meta_df["primary_dept_id"].astype(int)
        course_meta_df["is_cross"]        = course_meta_df["COURSECODE"].apply(
            lambda c: len(course_dept_mapping.get(c, set())) > 1
        )

        existing_courses = {
            c.code: c
            for c in Course.objects.filter(code__in=course_codes)
        }

        courses_to_create = []
        courses_to_update = []
        cross_dept_map    = {}  # code → [other dept ids]

        for row in course_meta_df.itertuples(index=False):
            c_dept_codes   = course_dept_mapping.get(row.COURSECODE, set())
            other_dept_ids = [
                dept_map[dc]
                for dc in (c_dept_codes - {row.primary_dept})
                if dc in dept_map
            ]
            if row.is_cross and other_dept_ids:
                cross_dept_map[row.COURSECODE] = other_dept_ids

            if row.COURSECODE in existing_courses:
                c = existing_courses[row.COURSECODE]
                c.title                 = row.COURSENAME
                c.credits               = row.CREDITS
                c.semester_id           = row.semester_id
                c.department_id         = row.primary_dept_id
                c.is_cross_departmental = row.is_cross
                courses_to_update.append(c)
            else:
                courses_to_create.append(
                    Course(
                        code=row.COURSECODE,
                        title=row.COURSENAME,
                        credits=row.CREDITS,
                        semester_id=row.semester_id,
                        department_id=row.primary_dept_id,
                        is_cross_departmental=row.is_cross,
                    )
                )

        # bulk_create + bulk_update instead of update_or_create loop
        if courses_to_create:
            Course.objects.bulk_create(courses_to_create, ignore_conflicts=True, batch_size=BATCH_SIZE)
            stats["courses_created"] += len(courses_to_create)

        if courses_to_update:
            Course.objects.bulk_update(
                courses_to_update,
                ["title", "credits", "semester_id", "department_id", "is_cross_departmental"],
                batch_size=BATCH_SIZE,
            )
            stats["courses_updated"] += len(courses_to_update)

        course_id_map = {
            r["code"]: r["id"]
            for r in Course.objects.filter(code__in=course_codes).values("id", "code")
        }

        # Batch associated_departments via through-model (was: .set() per course = N×3 queries)
        if cross_dept_map:
            cross_course_ids   = [course_id_map[c] for c in cross_dept_map if c in course_id_map]
            CourseAssociation  = Course.associated_departments.through
            CourseAssociation.objects.filter(course_id__in=cross_course_ids).delete()
            assoc_objs = [
                CourseAssociation(course_id=course_id_map[code], department_id=did)
                for code, dept_ids in cross_dept_map.items()
                if code in course_id_map
                for did in dept_ids
            ]
            if assoc_objs:
                CourseAssociation.objects.bulk_create(
                    assoc_objs, ignore_conflicts=True, batch_size=BATCH_SIZE
                )
            stats["courses_with_associations"] = len(cross_dept_map)

        progress_callback(
            4, TOTAL_STEPS,
            f"Courses done — "
            f"{stats.get('courses_created', 0):,} created, "
            f"{stats.get('courses_updated', 0):,} updated, "
            f"{stats.get('courses_with_associations', 0):,} cross-departmental",
            stats=dict(stats),
        )

        # ── Step 5: Course Groups ──────────────────────────────────────────────
        progress_callback(5, TOTAL_STEPS, "Processing course groups...")

        cg_pairs_df["course_id"] = cg_pairs_df["COURSECODE"].map(course_id_map)
        cg_pairs_df = cg_pairs_df.dropna(subset=["course_id"]).copy()
        cg_pairs_df["course_id"] = cg_pairs_df["course_id"].astype(int)

        existing_groups_df = _safe_df(
            CourseGroup.objects.filter(
                course__code__in=course_codes,
                group_name__in=uploaded_group_names,
            ).values("id", "group_name", "course_id"),
            columns=["id", "group_name", "course_id"],
        )

        merged_cg = cg_pairs_df.merge(
            existing_groups_df[["id", "group_name", "course_id"]],
            left_on=["course_id", "GROUP"],
            right_on=["course_id", "group_name"],
            how="left",
        )

        new_groups_df = merged_cg[merged_cg["id"].isna()]
        if not new_groups_df.empty:
            CourseGroup.objects.bulk_create(
                [
                    CourseGroup(group_name=row.GROUP, course_id=int(row.course_id))
                    for row in new_groups_df.itertuples(index=False)
                ],
                ignore_conflicts=True,
                batch_size=BATCH_SIZE,
            )
            stats["groups_created"] += len(new_groups_df)

        group_id_map = {
            (r["course_id"], r["group_name"]): r["id"]
            for r in CourseGroup.objects.filter(
                course__code__in=course_codes,
                group_name__in=uploaded_group_names,
            ).values("id", "group_name", "course_id")
        }

        # ── Step 6: Enrollments ────────────────────────────────────────────────
        progress_callback(6, TOTAL_STEPS, f"Processing {len(df):,} enrollment rows...")

        enr_df = (
            df[["STUDNUM_STR", "COURSECODE", "GROUP"]]
            .dropna(subset=["GROUP"])
            .drop_duplicates()
            .reset_index(drop=True)
            .copy()
        )

        enr_df["student_id"] = enr_df["STUDNUM_STR"].map(student_id_map)
        enr_df["course_id"]  = enr_df["COURSECODE"].map(course_id_map)

        # Vectorized group_id lookup
        enr_df["_cid_tmp"] = enr_df["COURSECODE"].map(course_id_map)
        enr_df["group_id"] = [
            group_id_map.get((cid, grp))
            for cid, grp in zip(enr_df["_cid_tmp"], enr_df["GROUP"])
        ]
        enr_df = enr_df.drop(columns=["_cid_tmp"])

        missing_groups = enr_df[enr_df["group_id"].isna()]
        for row in missing_groups.itertuples(index=False):
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

            # ── KEY FIX: filter by course_id (232 values) not student_id (22k values)
            progress_callback(6, TOTAL_STEPS, "Fetching existing enrollments...")
            existing_enr_df = _safe_df(
                Enrollment.objects.filter(
                    course_id__in=enr_df["course_id"].unique().tolist(),
                ).values("id", "student_id", "course_id", "group_id", "status"),
                columns=["id", "student_id", "course_id", "group_id", "status"],
            )

            progress_callback(6, TOTAL_STEPS, "Merging enrollment data...")
            merged_enr = enr_df.merge(
                existing_enr_df,
                on=["student_id", "course_id"],
                how="left",
                suffixes=("_new", "_existing"),
            )

            is_new      = merged_enr["id"].isna()
            is_existing = ~is_new

            g_new_col = "group_id_new"      if "group_id_new"      in merged_enr.columns else "group_id"
            g_ext_col = "group_id_existing" if "group_id_existing" in merged_enr.columns else "group_id"

            # Create new enrollments (chunked with progress)
            new_enr_df = merged_enr[is_new].drop_duplicates(
                subset=["student_id", "course_id"]
            ).copy()

            if not new_enr_df.empty:
                new_enrollments = [
                    Enrollment(
                        student_id=int(row.student_id),
                        course_id=int(row.course_id),
                        group_id=int(getattr(row, g_new_col)),
                        status="enrolled",
                    )
                    for row in new_enr_df.itertuples(index=False)
                ]
                total_enr = len(new_enrollments)
                for i in range(0, total_enr, BATCH_SIZE):
                    Enrollment.objects.bulk_create(
                        new_enrollments[i : i + BATCH_SIZE], ignore_conflicts=True
                    )
                    progress_callback(
                        6, TOTAL_STEPS,
                        f"Creating enrollments... {min(i + BATCH_SIZE, total_enr):,}/{total_enr:,}",
                    )
                stats["enrollments_created"] += total_enr

            # Update changed enrollments (chunked with progress)
            if is_existing.any():
                ext_rows     = merged_enr[is_existing].copy()
                needs_update = (
                    (ext_rows[g_new_col] != ext_rows[g_ext_col])
                    | (ext_rows["status"] != "enrolled")
                )
                update_df = ext_rows[needs_update]
                if not update_df.empty:
                    update_objs = [
                        Enrollment(
                            id=int(row.id),
                            group_id=int(getattr(row, g_new_col)),
                            status="enrolled",
                        )
                        for row in update_df.itertuples(index=False)
                    ]
                    total_upd = len(update_objs)
                    for i in range(0, total_upd, BATCH_SIZE):
                        Enrollment.objects.bulk_update(
                            update_objs[i : i + BATCH_SIZE],
                            ["group_id", "status"],
                        )
                        progress_callback(
                            6, TOTAL_STEPS,
                            f"Updating enrollments... {min(i + BATCH_SIZE, total_upd):,}/{total_upd:,}",
                        )
                    stats["enrollments_updated"] += total_upd

        progress_callback(
            6, TOTAL_STEPS,
            f"Enrollments done — "
            f"{stats['enrollments_created']:,} created, "
            f"{stats['enrollments_updated']:,} updated",
            stats=dict(stats),
        )

    # ── Step 8: Complete ───────────────────────────────────────────────────────
    progress_callback(8, TOTAL_STEPS, "Finalising...", stats=dict(stats))
    return {"stats": dict(stats), "errors": errors}


# ── Main View ──────────────────────────────────────────────────────────────────
class ImportEnrollmentsData(generics.GenericAPIView):
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, *args, **kwargs):
        file = request.FILES.get("myFile")
        selected_semester = request.data.get("selectedSemester")

        if not file:
            return Response({"error": "No file provided."}, status=400)

        file_bytes        = file.read()
        selected_semester = selected_semester

        async def event_stream():
            queue = asyncio.Queue()

            def progress_callback(step, total, message, stats=None):
                queue.put_nowait(_progress(step, total, message, stats))

            async def run_import():
                try:
                    result = await sync_to_async(_run_import, thread_sensitive=False)(
                        file_bytes, selected_semester, progress_callback
                    )
                    queue.put_nowait(_done(result["stats"], result["errors"]))
                except Exception as exc:
                    logger.error(f"Import failed: {exc}", exc_info=True)
                    queue.put_nowait(_error(f"Import failed: {str(exc)}"))
                finally:
                    queue.put_nowait(None)

            import_task = asyncio.create_task(run_import())

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                if event is None:
                    break

                yield event

            await import_task

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"]               = "no-cache"
        response["X-Accel-Buffering"]           = "no"
        response["Access-Control-Allow-Origin"] = "*"
        response["Connection"]                  = "keep-alive"
        return response