 
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

# Re-use the font / colour / canvas helpers from the existing reports module
from .views import (
    FONT_REGULAR, FONT_BOLD,
    PRIMARY, BLUE_HEADER, COL_HEADER, BORDER_COL,
    TEXT_DARK, TEXT_WHITE, SPACER_ROW,
    _NumberedCanvas, _s, _sb, _logo_and_header,
)

# ── Extra colours for attendance status ───────────────────────────────────────
PRESENT_GREEN  = colors.HexColor("#E6F4EA")
ABSENT_RED     = colors.HexColor("#FCE8E8")
CHEATED_AMBER  = colors.HexColor("#FFF3E0")
BADGE_GREEN    = colors.HexColor("#1E8449")
BADGE_RED      = colors.HexColor("#C0392B")
BADGE_AMBER    = colors.HexColor("#CC6600")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER — build attendance PDF
# ══════════════════════════════════════════════════════════════════════════════
def _build_attendance_pdf(timetable: MasterTimetable, exam: Exam, student_exams) -> bytes:
    """
    Portrait A4 attendance report for a single exam.
    Columns: #, Reg No, Name, Department, Sign-In, Sign-Out, Cheated
    Cheated rows get amber tint. Footer notes count summary.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=2.0 * cm,
        title=f"Attendance Report – Exam {exam.id}",
    )

    hdr  = _sb("AH",  fontSize=9,  textColor=TEXT_DARK,  alignment=TA_CENTER, leading=12)
    cell = _s("AC",   fontSize=8,  textColor=TEXT_DARK,  alignment=TA_LEFT,   leading=11)
    celc = _s("ACC",  fontSize=8,  textColor=TEXT_DARK,  alignment=TA_CENTER, leading=11)

    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic Year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()}"
    )

    course_title = (
        exam.group.course.title
        if exam.group and exam.group.course else "Unknown Course"
    )
    course_code = (
        exam.group.course.code
        if exam.group and exam.group.course else ""
    )
    group_name = exam.group.group_name if exam.group else "–"
    date_str   = exam.date.strftime("%d %B %Y") if exam.date else "–"
    time_str   = (
        f"{exam.start_time.strftime('%I:%M %p').lstrip('0')} – "
        f"{exam.end_time.strftime('%I:%M %p').lstrip('0')}"
        if exam.start_time and exam.end_time else "–"
    )
    room_str   = exam.room.name if exam.room else "No Room"

    report_title = f"ATTENDANCE REPORT – {timetable_lbl}"

    story = _logo_and_header(report_title, "")

    # ── Exam meta block ───────────────────────────────────────────────────────
    meta_data = [
        [
            Paragraph(f"<b>Course:</b> {course_code} – {course_title}", _s("M", fontSize=9)),
            Paragraph(f"<b>Group:</b> {group_name}", _s("M", fontSize=9, alignment=TA_CENTER)),
            Paragraph(f"<b>Room:</b> {room_str}", _s("M", fontSize=9, alignment=TA_CENTER)),
        ],
        [
            Paragraph(f"<b>Date:</b> {date_str}", _s("M", fontSize=9)),
            Paragraph(f"<b>Time:</b> {time_str}", _s("M", fontSize=9, alignment=TA_CENTER)),
            Paragraph(
                f"<b>Printed:</b> {timezone.now().strftime('%d %b %Y %H:%M')}",
                _s("M", fontSize=9, alignment=TA_RIGHT)
            ),
        ],
    ]
    meta_tbl = Table(meta_data, colWidths=["40%", "30%", "30%"])
    meta_tbl.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5, BORDER_COL),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#F0F4FA")),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # ── Fetch cheating reports keyed by student_id ────────────────────────────
    cheating_map = {
        cr.student_id: cr
        for cr in CheatingReport.objects.filter(exam=exam)
    }

    # ── Table data ────────────────────────────────────────────────────────────
    headers    = ["#", "Reg No", "Student Name", "Department", "Sign-In", "Sign-Out", "Cheated"]
    col_widths = [0.7*cm, 2.2*cm, 4.8*cm, 3.5*cm, 1.8*cm, 1.8*cm, 2.0*cm]

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

    total = signed_in = signed_out = cheated_count = absent_count = 0

    for idx, se in enumerate(student_exams, start=1):
        total += 1
        full_name  = f"{se.student.user.first_name} {se.student.user.last_name}".strip() if se.student and se.student.user else "–"
        reg_no     = se.student.reg_no if se.student else "–"
        dept_name  = se.student.department.name if se.student and se.student.department else "–"
        si         = se.signin_attendance
        so         = se.signout_attendance

        if si: signed_in += 1
        if so: signed_out += 1

        student_id = se.student_id
        has_report = student_id in cheating_map
        report_obj = cheating_map.get(student_id)

        if has_report: cheated_count += 1
        if not si:     absent_count += 1

        # Sign-in / sign-out cell
        def _tick(val):
            return Paragraph(
                f'<font color="{"#1E8449" if val else "#C0392B"}">{"✓" if val else "✗"}</font>',
                celc
            )

        # Cheated badge
        if has_report:
            severity_color = {
                "low": "#CC6600", "medium": "#E67E22", "high": "#C0392B"
            }.get(report_obj.severity, "#CC6600")
            cheated_cell = Paragraph(
                f'<font color="{severity_color}"><b>YES</b></font><br/>'
                f'<font size="6" color="{severity_color}">{report_obj.get_severity_display()}</font>',
                celc
            )
        else:
            cheated_cell = Paragraph('<font color="#1E8449">–</font>', celc)

        row_num = len(tbl_data)
        tbl_data.append([
            Paragraph(str(idx), celc),
            Paragraph(reg_no, cell),
            Paragraph(full_name, cell),
            Paragraph(dept_name, cell),
            _tick(si),
            _tick(so),
            cheated_cell,
        ])

        # Row tint
        if has_report:
            style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), CHEATED_AMBER))
        elif si:
            style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), PRESENT_GREEN))
        else:
            style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), ABSENT_RED))

    tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(KeepTogether(tbl))
    story.append(Spacer(1, 0.4 * cm))

    # ── Summary footer ────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.15 * cm))

    summary_data = [[
        Paragraph(f"<b>Total Students:</b> {total}", _s("Sum", fontSize=9)),
        Paragraph(f'<font color="#1E8449"><b>Signed In: {signed_in}</b></font>', _s("Sum", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f'<font color="#C0392B"><b>Absent: {absent_count}</b></font>', _s("Sum", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f'<font color="#CC6600"><b>Cheating Reports: {cheated_count}</b></font>', _s("Sum", fontSize=9, alignment=TA_CENTER)),
        Paragraph(f"<b>Signed Out: {signed_out}</b>", _s("Sum", fontSize=9, alignment=TA_RIGHT)),
    ]]
    sum_tbl = Table(summary_data, colWidths=["20%", "20%", "20%", "25%", "15%"])
    sum_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#F0F4FA")),
        ("BOX",          (0, 0), (-1, -1), 0.5, BORDER_COL),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(sum_tbl)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 1 — Dashboard Stats Cards
# ══════════════════════════════════════════════════════════════════════════════
class AttendanceStatsView(APIView):
    """
    GET /api/report/attendance/stats/?timetable_id=<id>

    Returns summary cards for a timetable:
    - total_students, signed_in, signed_out, absent, cheating_reports
    - breakdown by exam (for chart rendering)
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        timetable_id = request.GET.get("timetable_id")
        if not timetable_id:
            return Response({"error": "timetable_id is required."}, status=400)

        try:
            timetable = MasterTimetable.objects.get(pk=timetable_id)
        except MasterTimetable.DoesNotExist:
            return Response({"error": "Timetable not found."}, status=404)

        student_exams = StudentExam.objects.filter(
            exam__mastertimetableexam__master_timetable=timetable
        ).select_related("exam", "exam__group", "exam__group__course", "student")

        total        = student_exams.count()
        signed_in    = student_exams.filter(signin_attendance=True).count()
        signed_out   = student_exams.filter(signout_attendance=True).count()
        absent       = student_exams.filter(signin_attendance=False).count()
        cheating_reports = CheatingReport.objects.filter(
            exam__mastertimetableexam__master_timetable=timetable
        ).count()

        # Per-exam breakdown
        exams = Exam.objects.filter(
            mastertimetableexam__master_timetable=timetable
        ).select_related("group", "group__course", "room").distinct()

        exam_breakdown = []
        for exam in exams:
            ses       = student_exams.filter(exam=exam)
            exam_total = ses.count()
            exam_in    = ses.filter(signin_attendance=True).count()
            exam_cheat = CheatingReport.objects.filter(exam=exam).count()
            exam_breakdown.append({
                "exam_id":     exam.id,
                "course":      exam.group.course.title if exam.group and exam.group.course else "–",
                "course_code": exam.group.course.code  if exam.group and exam.group.course else "–",
                "group":       exam.group.group_name   if exam.group else "–",
                "date":        exam.date,
                "start_time":  exam.start_time,
                "end_time":    exam.end_time,
                "room":        exam.room.name if exam.room else "–",
                "status":      exam.status,
                "total":       exam_total,
                "signed_in":   exam_in,
                "absent":      exam_total - exam_in,
                "cheating_reports": exam_cheat,
            })

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
            "exams": exam_breakdown,
        })


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW 2 — Per-Exam Attendance List
# ══════════════════════════════════════════════════════════════════════════════
class ExamAttendanceListView(APIView):
    """
    GET /api/report/attendance/?exam_id=<id>

    Returns student list for a specific exam with:
    - signin/signout status
    - cheated: bool
    - cheating_report: {id, severity, status, incident_description} | null
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        exam_id = request.GET.get("exam_id")
        if not exam_id:
            return Response({"error": "exam_id is required."}, status=400)

        try:
            exam = Exam.objects.select_related(
                "group", "group__course", "room"
            ).get(pk=exam_id)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=404)

        student_exams = StudentExam.objects.filter(exam=exam).select_related(
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
                "department":      se.student.department.name if se.student and se.student.department else "–",
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
#  VIEW 3 — Admin Cheating Report Action (confirm / dismiss)
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
                status=400
            )

        if new_status:
            report.status = new_status
        report.admin_notes  = admin_notes
        report.reviewed_by  = request.user
        report.reviewed_at  = timezone.now()
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
    GET /api/report/attendance/pdf/?exam_id=<id>
    Downloads a PDF attendance report for a specific exam.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        exam_id = request.GET.get("exam_id")
        if not exam_id:
            return Response({"error": "exam_id is required."}, status=400)

        try:
            exam = Exam.objects.select_related(
                "group", "group__course", "room", "master_timetable",
                "master_timetable__location", "master_timetable__semester",
            ).get(pk=exam_id)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=404)

        timetable = exam.master_timetable
        if not timetable:
            return Response({"error": "Exam has no associated timetable."}, status=400)

        student_exams = StudentExam.objects.filter(exam=exam).select_related(
            "student", "student__user", "student__department"
        ).order_by("student__reg_no")

        try:
            pdf_bytes = _build_attendance_pdf(timetable, exam, student_exams)
        except Exception as exc:
            return Response(
                {"error": f"PDF generation failed: {exc}"}, status=500
            )

        course_code = (
            exam.group.course.code.replace(" ", "_")
            if exam.group and exam.group.course else "exam"
        )
        filename = f"attendance_{course_code}_{exam.date}_{timezone.now().strftime('%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response