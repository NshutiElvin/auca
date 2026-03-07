import io
from collections import defaultdict

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from exams.models import Exam, StudentExam
from schedules.models import MasterTimetable
from cheating.models import CheatingReport

from .views import (
    FONT_REGULAR, FONT_BOLD,
    PRIMARY, BLUE_HEADER, COL_HEADER, BORDER_COL,
    TEXT_DARK, TEXT_WHITE, SPACER_ROW,
    _NumberedCanvas, _s, _sb, _logo_and_header,
)

# ── Extra colours ─────────────────────────────────────────────────────────────
PRESENT_GREEN    = colors.HexColor("#E6F4EA")
ABSENT_RED       = colors.HexColor("#FCE8E8")
CHEATED_AMBER    = colors.HexColor("#FFF3E0")
BADGE_GREEN      = colors.HexColor("#1E8449")
BADGE_RED        = colors.HexColor("#C0392B")
BADGE_AMBER      = colors.HexColor("#CC6600")
COURSE_HEADER_BG = colors.HexColor("#D6E4F7")


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS — campus-safe querysets
#
#  Mirrors exactly how TimetablePDFView (views.py) scopes its exams:
#    mastertimetableexam__master_timetable=timetable   (M2M join filter)
#    master_timetable=timetable                        (direct FK filter)
# ══════════════════════════════════════════════════════════════════════════════
def _timetable_exams(timetable: MasterTimetable, extra_filters: dict = None):
    """
    Return an Exam queryset scoped exclusively to `timetable`.
    Mirrors: Exam.objects.filter(
        mastertimetableexam__master_timetable_id=timetable.id,
        master_timetable=timetable
    ) from TimetablePDFView.
    """
    qs = Exam.objects.filter(
        mastertimetableexam__master_timetable=timetable,
        master_timetable=timetable,
        

    ).distinct()
    if extra_filters:
        qs = qs.filter(**extra_filters)
    return qs


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER — build attendance PDF  (grouped by course)
# ══════════════════════════════════════════════════════════════════════════════
def _build_attendance_pdf(timetable: MasterTimetable, student_exams) -> bytes:
    """
    Portrait A4 attendance report for a whole timetable, grouped by course.

    Layout
    ──────
    For every course:
      • A full-width course header band  (code – title)
      • One sub-header row per exam      (date / time / room / group)
      • Data rows for that exam's students

    Footer: summary per course + grand total.

    `student_exams` must already be campus-scoped (via exam_id__in).
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm,  bottomMargin=2.0 * cm,
        title="Attendance Report",
    )

    hdr  = _sb("AH",  fontSize=9, textColor=TEXT_DARK,  alignment=TA_CENTER, leading=12)
    cell = _s("AC",   fontSize=8, textColor=TEXT_DARK,  alignment=TA_LEFT,   leading=11)
    celc = _s("ACC",  fontSize=8, textColor=TEXT_DARK,  alignment=TA_CENTER, leading=11)

    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic Year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()}"
    )
    report_title = f"ATTENDANCE REPORT – {timetable_lbl}"

    story = _logo_and_header(report_title, "")
    story.append(Paragraph(
        f"<b>Printed:</b> {timezone.now().strftime('%d %b %Y %H:%M')}",
        _s("M", fontSize=9, alignment=TA_RIGHT)
    ))
    story.append(Spacer(1, 0.3 * cm))

    # ── Pre-load cheating reports scoped to this timetable's exams only ───────
    timetable_exam_ids = list(
        _timetable_exams(timetable).values_list("id", flat=True)
    )
    cheating_map = {
        (cr.exam_id, cr.student_id): cr
        for cr in CheatingReport.objects.filter(
            exam_id__in=timetable_exam_ids
        ).select_related("reported_by")
    }

    col_widths   = [0.7*cm, 2.2*cm, 4.8*cm, 3.0*cm, 1.8*cm, 1.8*cm, 2.0*cm]
    headers      = ["#", "Reg No", "Student Name", "Department", "Sign-In", "Sign-Out", "Cheated"]
    usable_width = sum(col_widths)

    # ── Aggregate by course then by exam ──────────────────────────────────────
    course_exam_map = defaultdict(lambda: defaultdict(list))
    for se in student_exams:
        course = se.exam.group.course if se.exam and se.exam.group else None
        c_key  = (
            course.code  if course else "–",
            course.title if course else "Unknown Course",
        )
        course_exam_map[c_key][se.exam].append(se)

    course_exam_map = dict(sorted(course_exam_map.items(), key=lambda x: x[0][0]))

    grand = dict(total=0, signed_in=0, signed_out=0, absent=0, cheated=0)
    course_summaries = []

    def _tick(val):
        colour = "#1E8449" if val else "#C0392B"
        mark   = "✓" if val else "✗"
        return Paragraph(f'<font color="{colour}">{mark}</font>', celc)

    for (c_code, c_title), exam_dict in course_exam_map.items():
        # ── Course banner ─────────────────────────────────────────────────────
        course_banner = Table(
            [[Paragraph(
                f'<b>{c_code} – {c_title}</b>',
                _s("CB", fontSize=10, textColor=TEXT_DARK, alignment=TA_LEFT, leading=14)
            )]],
            colWidths=[usable_width],
        )
        course_banner.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), COURSE_HEADER_BG),
            ("BOX",           (0, 0), (-1, -1), 0.8, BORDER_COL),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ]))
        story.append(KeepTogether(course_banner))

        c_total = c_in = c_out = c_absent = c_cheated = 0

        for exam in sorted(exam_dict.keys(), key=lambda e: (e.date, e.start_time)):
            ses = exam_dict[exam]

            date_str  = exam.date.strftime("%d %B %Y") if exam.date else "–"
            time_str  = (
                f"{exam.start_time.strftime('%I:%M %p').lstrip('0')} – "
                f"{exam.end_time.strftime('%I:%M %p').lstrip('0')}"
                if exam.start_time and exam.end_time else "–"
            )
            room_str  = exam.room.name if exam.room else "No Room"
            group_str = exam.group.group_name if exam.group else "–"

            exam_subhdr = Table(
                [[Paragraph(
                    f"Group: <b>{group_str}</b> &nbsp;|&nbsp; "
                    f"Date: <b>{date_str}</b> &nbsp;|&nbsp; "
                    f"Time: <b>{time_str}</b> &nbsp;|&nbsp; "
                    f"Room: <b>{room_str}</b>",
                    _s("EH", fontSize=8, textColor=TEXT_DARK, alignment=TA_LEFT, leading=12)
                )]],
                colWidths=[usable_width],
            )
            exam_subhdr.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#EEF2F9")),
                ("BOX",           (0, 0), (-1, -1), 0.4, BORDER_COL),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ]))

            tbl_data   = [[Paragraph(h, hdr) for h in headers]]
            style_cmds = [
                ("BACKGROUND",    (0, 0), (-1, 0),  COL_HEADER),
                ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_COL),
                ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ]

            for idx, se in enumerate(
                sorted(ses, key=lambda s: s.student.reg_no if s.student else ""),
                start=1,
            ):
                si = se.signin_attendance
                so = se.signout_attendance
                full_name = (
                    f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                    if se.student and se.student.user else "–"
                )
                reg_no    = se.student.reg_no if se.student else "–"
                dept_name = (
                    se.student.department.name
                    if se.student and se.student.department else "–"
                )

                has_report = (exam.id, se.student_id) in cheating_map
                report_obj = cheating_map.get((exam.id, se.student_id))

                if si:         c_in      += 1
                if so:         c_out     += 1
                if not si:     c_absent  += 1
                if has_report: c_cheated += 1
                c_total += 1

                if has_report:
                    sev_color = {
                        "low": "#CC6600", "medium": "#E67E22", "high": "#C0392B"
                    }.get(report_obj.severity, "#CC6600")
                    cheated_cell = Paragraph(
                        f'<font color="{sev_color}"><b>YES</b></font><br/>'
                        f'<font size="6" color="{sev_color}">{report_obj.get_severity_display()}</font>',
                        celc
                    )
                else:
                    cheated_cell = Paragraph('<font color="#1E8449">–</font>', celc)

                row_num = len(tbl_data)
                tbl_data.append([
                    Paragraph(str(idx), celc),
                    Paragraph(reg_no,    cell),
                    Paragraph(full_name, cell),
                    Paragraph(dept_name, cell),
                    _tick(si),
                    _tick(so),
                    cheated_cell,
                ])

                if has_report:
                    style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), CHEATED_AMBER))
                elif si:
                    style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), PRESENT_GREEN))
                else:
                    style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), ABSENT_RED))

            data_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
            data_tbl.setStyle(TableStyle(style_cmds))

            story.append(KeepTogether([exam_subhdr, data_tbl]))
            story.append(Spacer(1, 0.2 * cm))

        # ── Per-course summary row ────────────────────────────────────────────
        story.append(Spacer(1, 0.1 * cm))
        c_summary_data = [[
            Paragraph(f"<b>{c_code} Total:</b> {c_total}",                        _s("S", fontSize=8)),
            Paragraph(f'<font color="#1E8449"><b>In: {c_in}</b></font>',           _s("S", fontSize=8, alignment=TA_CENTER)),
            Paragraph(f'<font color="#C0392B"><b>Absent: {c_absent}</b></font>',   _s("S", fontSize=8, alignment=TA_CENTER)),
            Paragraph(f'<font color="#CC6600"><b>Cheated: {c_cheated}</b></font>', _s("S", fontSize=8, alignment=TA_CENTER)),
            Paragraph(f"<b>Out: {c_out}</b>",                                     _s("S", fontSize=8, alignment=TA_RIGHT)),
        ]]
        c_sum_tbl = Table(c_summary_data, colWidths=["22%", "18%", "20%", "22%", "18%"])
        c_sum_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), COURSE_HEADER_BG),
            ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_COL),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(c_sum_tbl)
        story.append(Spacer(1, 0.4 * cm))

        grand["total"]      += c_total
        grand["signed_in"]  += c_in
        grand["signed_out"] += c_out
        grand["absent"]     += c_absent
        grand["cheated"]    += c_cheated

        course_summaries.append({
            "code": c_code, "title": c_title,
            "total": c_total, "signed_in": c_in,
            "absent": c_absent, "cheated": c_cheated, "signed_out": c_out,
        })

    # ── Grand total footer ────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.grey))
    story.append(Spacer(1, 0.15 * cm))
    grand_data = [[
        Paragraph(f"<b>GRAND TOTAL: {grand['total']}</b>",                               _s("G", fontSize=9)),
        Paragraph(f'<font color="#1E8449"><b>Signed In: {grand["signed_in"]}</b></font>', _s("G", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f'<font color="#C0392B"><b>Absent: {grand["absent"]}</b></font>',        _s("G", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f'<font color="#CC6600"><b>Cheating: {grand["cheated"]}</b></font>',     _s("G", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f"<b>Signed Out: {grand['signed_out']}</b>",                            _s("G", fontSize=9, alignment=TA_RIGHT)),
    ]]
    grand_tbl = Table(grand_data, colWidths=["22%", "20%", "18%", "22%", "18%"])
    grand_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#D6E4F7")),
        ("BOX",           (0, 0), (-1, -1), 1.0, BORDER_COL),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(grand_tbl)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 1 — Dashboard Stats Cards  (grouped by course)
# ══════════════════════════════════════════════════════════════════════════════
class AttendanceStatsView(APIView):
    """
    GET /api/report/attendance/stats/?timetable_id=<id>
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        timetable_id = request.GET.get("timetable_id")
        if not timetable_id:
            return Response({"error": "timetable_id is required."}, status=400)

        try:
            timetable = MasterTimetable.objects.select_related(
                "location", "semester"
            ).get(pk=timetable_id)
        except MasterTimetable.DoesNotExist:
            return Response({"error": "Timetable not found."}, status=404)

        # Get exams scoped to this timetable
        exam_qs = _timetable_exams(timetable).select_related(
            "group", "group__course", "room"
        )
        exam_ids = list(exam_qs.values_list("id", flat=True))

        # FIXED: Get StudentExam records only for these exams
        student_exams = StudentExam.objects.filter(
            exam_id__in=exam_ids,
            student__department__location=timetable.location,

        ).select_related(
            "exam",
            "exam__group",
            "exam__group__course",
            "exam__room",
            "student",
        )

        total      = student_exams.count()
        signed_in  = student_exams.filter(signin_attendance=True).count()
        signed_out = student_exams.filter(signout_attendance=True).count()
        absent     = student_exams.filter(signin_attendance=False).count()

        cheating_reports = CheatingReport.objects.filter(
            exam_id__in=exam_ids,
        ).count()

        course_map = defaultdict(lambda: {
            "course_code": "", "course_title": "",
            "total": 0, "signed_in": 0, "absent": 0, "cheating_reports": 0,
            "exams": [],
        })

        for exam in exam_qs:
            course  = exam.group.course if exam.group else None
            c_code  = course.code  if course else "–"
            c_title = course.title if course else "Unknown Course"
            key     = f"{c_code}||{c_title}"

            # Filter student exams for this specific exam
            ses = student_exams.filter(exam=exam)
            exam_total = ses.count()
            exam_in    = ses.filter(signin_attendance=True).count()
            exam_cheat = CheatingReport.objects.filter(exam=exam).count()

            bucket = course_map[key]
            bucket["course_code"]       = c_code
            bucket["course_title"]      = c_title
            bucket["total"]            += exam_total
            bucket["signed_in"]        += exam_in
            bucket["absent"]           += exam_total - exam_in
            bucket["cheating_reports"] += exam_cheat
            bucket["exams"].append({
                "exam_id":          exam.id,
                "group":            exam.group.group_name if exam.group else "–",
                "date":             exam.date,
                "start_time":       exam.start_time,
                "end_time":         exam.end_time,
                "room":             exam.room.name if exam.room else "–",
                "status":           exam.status,
                "total":            exam_total,
                "signed_in":        exam_in,
                "absent":           exam_total - exam_in,
                "cheating_reports": exam_cheat,
            })

        courses = sorted(course_map.values(), key=lambda c: c["course_code"])

        return Response({
            "timetable_id":    timetable.id,
            "timetable_label": (
                f"{timetable.location.name} | {timetable.academic_year} | "
                f"{timetable.semester.name} ({timetable.category})"
            ),
            "stats": {
                "total_students":   total,
                "signed_in":        signed_in,
                "signed_out":       signed_out,
                "absent":           absent,
                "cheating_reports": cheating_reports,
            },
            "courses": courses,
        })


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 2 — Per-Course Attendance List
# ══════════════════════════════════════════════════════════════════════════════
class ExamAttendanceListView(APIView):
    """
    GET /api/report/attendance/?course_code=<code>&timetable_id=<id>
    GET /api/report/attendance/?exam_id=<id>   (legacy)
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        exam_id      = request.GET.get("exam_id")
        course_code  = request.GET.get("course_code")
        timetable_id = request.GET.get("timetable_id")

        if exam_id:
            # legacy: need timetable_id too for proper scoping
            if not timetable_id:
                return Response(
                    {"error": "timetable_id is required alongside exam_id."},
                    status=400,
                )
            try:
                timetable = MasterTimetable.objects.select_related(
                    "location", "semester"
                ).get(pk=timetable_id)
            except MasterTimetable.DoesNotExist:
                return Response({"error": "Timetable not found."}, status=404)
            return self._single_exam(request, exam_id, timetable)

        if not course_code or not timetable_id:
            return Response(
                {"error": "Provide either (exam_id + timetable_id) OR (course_code + timetable_id)."},
                status=400,
            )

        try:
            timetable = MasterTimetable.objects.select_related(
                "location", "semester"
            ).get(pk=timetable_id)
        except MasterTimetable.DoesNotExist:
            return Response({"error": "Timetable not found."}, status=404)

        exam_qs = _timetable_exams(
            timetable,
            extra_filters={"group__course__code": course_code},
        ).select_related("group", "group__course", "room")

        if not exam_qs.exists():
            return Response({"error": "No exams found for this course/timetable."}, status=404)

        exam_ids = list(exam_qs.values_list("id", flat=True))
        cheating_map = {
            (cr.exam_id, cr.student_id): cr
            for cr in CheatingReport.objects.filter(
                exam_id__in=exam_ids
            ).select_related("reported_by", "reviewed_by")
        }

        course_obj  = exam_qs.first().group.course
        exam_groups = []
        grand = dict(total=0, signed_in=0, signed_out=0, absent=0, cheating_reports=0)

        for exam in exam_qs.order_by("date", "start_time"):
            # FIXED: Get StudentExam records only for this exam
            student_exams = StudentExam.objects.filter(
                exam=exam
            ).select_related(
                "student", "student__user", "student__department", "room"
            ).order_by("student__reg_no")

            rows = []
            for se in student_exams:
                report = cheating_map.get((exam.id, se.student_id))
                rows.append({
                    "id":              se.id,
                    "student_id":      se.student_id,
                    "reg_no":          se.student.reg_no if se.student else "–",
                    "name":            (
                        f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                        if se.student and se.student.user else "–"
                    ),
                    "department":      (
                        se.student.department.name
                        if se.student and se.student.department else "–"
                    ),
                    "signin":          se.signin_attendance,
                    "signout":         se.signout_attendance,
                    "status":          se.status,
                    "cheated":         report is not None,
                    "cheating_report": {
                        "id":                   report.id,
                        "severity":             report.severity,
                        "status":               report.status,
                        "incident_description": report.incident_description,
                        "reported_by":          report.reported_by.get_full_name() if report.reported_by else "–",
                        "created_at":           report.created_at,
                        "evidence_count":       report.evidence.count(),
                    } if report else None,
                })

            exam_summary = {
                "total":            len(rows),
                "signed_in":        sum(1 for r in rows if r["signin"]),
                "signed_out":       sum(1 for r in rows if r["signout"]),
                "absent":           sum(1 for r in rows if not r["signin"]),
                "cheating_reports": sum(1 for r in rows if r["cheated"]),
            }
            for k in grand:
                grand[k] += exam_summary[k]

            exam_groups.append({
                "exam": {
                    "id":         exam.id,
                    "group":      exam.group.group_name if exam.group else "–",
                    "date":       exam.date,
                    "start_time": exam.start_time,
                    "end_time":   exam.end_time,
                    "room":       exam.room.name if exam.room else "–",
                    "status":     exam.status,
                },
                "students": rows,
                "summary":  exam_summary,
            })

        return Response({
            "course": {
                "code":  course_obj.code,
                "title": course_obj.title,
            },
            "timetable_id": timetable.id,
            "exam_groups":  exam_groups,
            "summary":      grand,
        })

    # ── Legacy single-exam helper ─────────────────────────────────────────────
    def _single_exam(self, request, exam_id, timetable: MasterTimetable):
        try:
            exam = Exam.objects.select_related(
                "group", "group__course", "room"
            ).get(pk=exam_id, master_timetable=timetable)  # locked to timetable
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found in this timetable."}, status=404)

        # FIXED: Get StudentExam records only for this exam
        student_exams = StudentExam.objects.filter(
            exam=exam
        ).select_related(
            "student", "student__user", "student__department", "room"
        ).order_by("student__reg_no")

        cheating_map = {
            cr.student_id: cr
            for cr in CheatingReport.objects.filter(exam=exam).select_related(
                "reported_by", "reviewed_by"
            )
        }

        rows = []
        for se in student_exams:
            report = cheating_map.get(se.student_id)
            rows.append({
                "id":              se.id,
                "student_id":      se.student_id,
                "reg_no":          se.student.reg_no if se.student else "–",
                "name":            (
                    f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                    if se.student and se.student.user else "–"
                ),
                "department":      (
                    se.student.department.name
                    if se.student and se.student.department else "–"
                ),
                "signin":          se.signin_attendance,
                "signout":         se.signout_attendance,
                "status":          se.status,
                "cheated":         report is not None,
                "cheating_report": {
                    "id":                   report.id,
                    "severity":             report.severity,
                    "status":               report.status,
                    "incident_description": report.incident_description,
                    "reported_by":          report.reported_by.get_full_name() if report.reported_by else "–",
                    "created_at":           report.created_at,
                    "evidence_count":       report.evidence.count(),
                } if report else None,
            })

        return Response({
            "exam": {
                "id":          exam.id,
                "course":      exam.group.course.title if exam.group and exam.group.course else "–",
                "course_code": exam.group.course.code  if exam.group and exam.group.course else "–",
                "group":       exam.group.group_name   if exam.group else "–",
                "date":        exam.date,
                "start_time":  exam.start_time,
                "end_time":    exam.end_time,
                "room":        exam.room.name if exam.room else "–",
                "status":      exam.status,
            },
            "students": rows,
            "summary": {
                "total":            len(rows),
                "signed_in":        sum(1 for r in rows if r["signin"]),
                "signed_out":       sum(1 for r in rows if r["signout"]),
                "absent":           sum(1 for r in rows if not r["signin"]),
                "cheating_reports": sum(1 for r in rows if r["cheated"]),
            },
        })


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 3 — Admin Cheating Report Action
# ══════════════════════════════════════════════════════════════════════════════
class CheatingReportActionView(APIView):
    """
    PATCH /api/report/cheating/<report_id>/action/
    Body: { "status": "confirmed"|"dismissed"|"under_review", "admin_notes": "..." }
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def patch(self, request, report_id):
        try:
            report = CheatingReport.objects.get(pk=report_id)
        except CheatingReport.DoesNotExist:
            return Response({"error": "Report not found."}, status=404)

        new_status   = request.data.get("status")
        admin_notes  = request.data.get("admin_notes", report.admin_notes)
        valid_states = [s[0] for s in CheatingReport.Status.choices]

        if new_status and new_status not in valid_states:
            return Response(
                {"error": f"Invalid status. Choose from: {valid_states}"},
                status=400,
            )

        if new_status:
            report.status = new_status
        report.admin_notes = admin_notes
        report.reviewed_by = request.user
        report.reviewed_at = timezone.now()
        report.save()

        return Response({
            "id":          report.id,
            "status":      report.status,
            "admin_notes": report.admin_notes,
            "reviewed_by": request.user.get_full_name(),
            "reviewed_at": report.reviewed_at,
        })


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 4 — Attendance PDF Export
# ══════════════════════════════════════════════════════════════════════════════
class AttendancePDFView(APIView):
    """
    GET /api/report/attendance/pdf/?timetable_id=<id>
    GET /api/report/attendance/pdf/?timetable_id=<id>&course_code=<code>
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        timetable_id = request.GET.get("timetable_id")
        course_code  = request.GET.get("course_code")

        if not timetable_id:
            return Response({"error": "timetable_id is required."}, status=400)

        try:
            timetable = MasterTimetable.objects.select_related(
                "location", "semester"
            ).get(pk=timetable_id)
        except MasterTimetable.DoesNotExist:
            return Response({"error": "Timetable not found."}, status=404)

        # Get exams scoped to this timetable
        extra = {"group__course__code": course_code} if course_code else None
        exam_qs = _timetable_exams(timetable, extra_filters=extra).select_related(
            "group", "group__course", "room"
        )

        if course_code and not exam_qs.exists():
            return Response(
                {"error": f"No exams found for course {course_code}."},
                status=404,
            )

        # FIXED: Get StudentExam records only for these exams
        exam_ids = list(exam_qs.values_list('id', flat=True))
        student_exams = StudentExam.objects.filter(
            exam_id__in=exam_ids,
            student__department__location=timetable.location,
        ).select_related(
            "exam",
            "exam__group",
            "exam__group__course",
            "exam__room",
            "student",
            "student__user",
            "student__department",
        ).order_by(
            "exam__group__course__code",
            "exam__date",
            "exam__start_time",
            "student__reg_no"
        )

        if not student_exams.exists():
            return Response(
                {"error": "No student exam records found for this timetable."},
                status=404,
            )

        try:
            pdf_bytes = _build_attendance_pdf(timetable, student_exams)
        except Exception as exc:
            return Response({"error": f"PDF generation failed: {exc}"}, status=500)

        suffix   = f"_{course_code}" if course_code else ""
        filename = (
            f"attendance{suffix}_{timetable.academic_year}_"
            f"{timetable.semester.name}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response