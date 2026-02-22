from rest_framework import generics
from rest_framework.response import Response
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
import os
import io
from django.utils import timezone

from exams.models import Exam, StudentExam
from schedules.models import MasterTimetable      


 

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def _register_century_gothic() -> tuple:
    
    alias_reg      = "CenturyGothic"
    alias_bold     = "CenturyGothic-Bold"
    alias_italic   = "CenturyGothic-Italic"
    alias_bold_ita = "CenturyGothic-BoldItalic"

    reg_path      = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path     = os.path.join(FONT_DIR, "centurygothic_bold.ttf")
    italic_path   = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_ita_path = os.path.join(FONT_DIR, "centurygothic_bold.ttf")

    for label, path in [("Regular  → centurygothic.ttf",  reg_path),
                         ("Bold     → centurygothic_bold.ttf", bold_path)]:
        if not os.path.isfile(path):
            raise RuntimeError(
                f"Century Gothic {label} not found.\n"
                f"Expected location: {path}"
            )

    pdfmetrics.registerFont(TTFont(alias_reg,  reg_path))
    pdfmetrics.registerFont(TTFont(alias_bold, bold_path))

    if os.path.isfile(italic_path):
        pdfmetrics.registerFont(TTFont(alias_italic, italic_path))
    if os.path.isfile(bold_ita_path):
        pdfmetrics.registerFont(TTFont(alias_bold_ita, bold_ita_path))

    registered = pdfmetrics.getRegisteredFontNames()
    registerFontFamily(
        alias_reg,
        normal=alias_reg,
        bold=alias_bold,
        italic=alias_italic   if alias_italic   in registered else alias_reg,
        boldItalic=alias_bold_ita if alias_bold_ita in registered else alias_bold,
    )

    return alias_reg, alias_bold


# Registered once at module import
FONT_REGULAR, FONT_BOLD = _register_century_gothic()


# ── Colour palette ────────────────────────────────────────────────────────────
PRIMARY    = colors.HexColor("#1A3C5E")
SECONDARY  = colors.HexColor("#2E86C1")
ACCENT     = colors.HexColor("#D4E6F1")
ROW_EVEN   = colors.HexColor("#F2F9FF")
ROW_ODD    = colors.white
BORDER     = colors.HexColor("#AED6F1")
TEXT_DARK  = colors.HexColor("#1B2631")
TEXT_LIGHT = colors.white


# ── Numbered-page canvas ──────────────────────────────────────────────────────
class _NumberedCanvas(rl_canvas.Canvas):
    """Renders a 'Page X of Y' footer on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total):
        self.saveState()
        w, _ = self._pagesize
        self.setFont(FONT_REGULAR, 8)
        self.setFillColor(colors.HexColor("#7F8C8D"))
        self.drawString(
            1.5 * cm, 0.8 * cm,
            f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        )
        self.drawRightString(
            w - 1.5 * cm, 0.8 * cm,
            f"Page {self._pageNumber} of {total}",
        )
        self.restoreState()


# ── Style factory ─────────────────────────────────────────────────────────────
def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CGTitle", parent=base["Title"],
            fontName=FONT_BOLD, fontSize=20,
            textColor=PRIMARY, spaceAfter=4, alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "CGSubtitle", parent=base["Normal"],
            fontName=FONT_REGULAR, fontSize=11,
            textColor=SECONDARY, spaceAfter=2, alignment=TA_CENTER,
        ),
        "section": ParagraphStyle(
            "CGSection", parent=base["Heading2"],
            fontName=FONT_BOLD, fontSize=13,
            textColor=PRIMARY, spaceBefore=14, spaceAfter=5,
        ),
        "header_cell": ParagraphStyle(
            "CGHeaderCell", parent=base["Normal"],
            fontName=FONT_BOLD, fontSize=8, leading=10,
            textColor=TEXT_LIGHT, alignment=TA_CENTER,
        ),
        "cell": ParagraphStyle(
            "CGCell", parent=base["Normal"],
            fontName=FONT_REGULAR, fontSize=8, leading=10,
            textColor=TEXT_DARK, alignment=TA_LEFT,
        ),
        "cell_center": ParagraphStyle(
            "CGCellCenter", parent=base["Normal"],
            fontName=FONT_REGULAR, fontSize=8, leading=10,
            textColor=TEXT_DARK, alignment=TA_CENTER,
        ),
        "big_num": ParagraphStyle(
            "CGBigNum", parent=base["Normal"],
            fontName=FONT_BOLD, fontSize=20,
            textColor=PRIMARY, alignment=TA_CENTER,
        ),
        "badge_active": ParagraphStyle(
            "CGBadgeActive", parent=base["Normal"],
            fontName=FONT_BOLD, fontSize=9,
            textColor=colors.HexColor("#1E8449"), alignment=TA_CENTER,
        ),
        "badge_inactive": ParagraphStyle(
            "CGBadgeInactive", parent=base["Normal"],
            fontName=FONT_BOLD, fontSize=9,
            textColor=colors.HexColor("#C0392B"), alignment=TA_CENTER,
        ),
    }


# ── PDF builder ───────────────────────────────────────────────────────────────
def _build_exam_timetable_pdf(timetable: MasterTimetable, exams) -> bytes:
    """
    Build and return a landscape A4 exam timetable PDF as raw bytes.

    Parameters
    ----------
    timetable : MasterTimetable
        The master timetable record (used for the report header).
    exams : QuerySet[Exam]
        Pre-filtered Exam queryset — already scoped to the timetable_id.
    """
    buffer = io.BytesIO()
    S = _styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=2 * cm,   bottomMargin=1.8 * cm,
        title=f"Exam Timetable – {timetable.name if hasattr(timetable, 'name') else timetable.id}",
        author="Academic Scheduling System",
    )

    # Eager-load everything we need in one DB round-trip
    exams = exams.select_related(
        "group",
        "group__course",
        "group__course__department",
        "room",
    ).prefetch_related(
        "studentexam_set__student__user",
        "studentexam_set__room",
    ).order_by("date", "start_time")

    story = []

    # ── Cover / header ────────────────────────────────────────────────────────
    timetable_label = getattr(timetable, "name", None) or f"ID {timetable.id}"
    story.append(Paragraph("Exam Timetable", S["title"]))
    story.append(Paragraph(timetable_label, S["subtitle"]))
    story.append(Paragraph(
        f"Report generated: {timezone.now().strftime('%d %b %Y, %H:%M')}",
        S["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=14))

    # ── Summary stats ─────────────────────────────────────────────────────────
    total_exams    = exams.count()
    total_students = StudentExam.objects.filter(exam__in=exams).count()
    unique_rooms   = exams.values("room_id").distinct().count()
    unique_groups  = exams.values("group_id").distinct().count()

    summary_data = [
        [Paragraph(h, S["header_cell"]) for h in
         ["Total Exams", "Exam Groups", "Rooms Used", "Total Students"]],
        [
            Paragraph(str(total_exams),    S["big_num"]),
            Paragraph(str(unique_groups),  S["big_num"]),
            Paragraph(str(unique_rooms),   S["big_num"]),
            Paragraph(str(total_students), S["big_num"]),
        ],
    ]
    summary_tbl = Table(summary_data, colWidths=["25%"] * 4)
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("BACKGROUND",    (0, 1), (-1, 1), ACCENT),
        ("BOX",           (0, 0), (-1, -1), 1,   BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(summary_tbl)
    story.append(Spacer(1, 0.6 * cm))

    # ── Exam schedule table ───────────────────────────────────────────────────
    story.append(Paragraph("Exam Schedule", S["section"]))

    headers = ["Date", "Slot", "Start", "End", "Course", "Group", "Room", "Status", "Students"]
    tbl_data = [[Paragraph(h, S["header_cell"]) for h in headers]]

    for exam in exams:
        course_code = (
            exam.group.course.code
            if exam.group and exam.group.course else "–"
        )
        group_name  = exam.group.group_name if exam.group else "–"
        room_name   = exam.room.name        if exam.room  else "–"
        enrolled    = exam.studentexam_set.filter(status="present").count()
        total_in_exam = exam.studentexam_set.count()

        status_style = (
            S["badge_active"] if exam.status == "active"
            else S["badge_inactive"]
        )

        tbl_data.append([
            Paragraph(exam.date.strftime("%d %b %Y") if exam.date else "–", S["cell_center"]),
            Paragraph(exam.slot_name or "–",                                 S["cell_center"]),
            Paragraph(exam.start_time.strftime("%H:%M") if exam.start_time else "–", S["cell_center"]),
            Paragraph(exam.end_time.strftime("%H:%M")   if exam.end_time   else "–", S["cell_center"]),
            Paragraph(course_code,                                           S["cell"]),
            Paragraph(group_name,                                            S["cell"]),
            Paragraph(room_name,                                             S["cell"]),
            Paragraph(exam.status or "–",                                    status_style),
            Paragraph(f"{enrolled}/{total_in_exam}",                         S["cell_center"]),
        ])

    exam_tbl = Table(
        tbl_data,
        colWidths=["11%", "8%", "7%", "7%", "16%", "12%", "13%", "10%", "10%"],
        repeatRows=1,
    )
    exam_tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), PRIMARY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_ODD, ROW_EVEN]),
        ("BOX",            (0, 0), (-1, -1), 1,   PRIMARY),
        ("INNERGRID",      (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
    ]))
    story.append(exam_tbl)
    story.append(Spacer(1, 0.6 * cm))

    # ── Per-exam student listing ──────────────────────────────────────────────
    story.append(Paragraph("Student Seating Details", S["section"]))

    for exam in exams:
        course_code = (
            exam.group.course.code
            if exam.group and exam.group.course else "–"
        )
        group_name = exam.group.group_name if exam.group else "–"
        date_str   = exam.date.strftime("%d %b %Y") if exam.date else "–"
        slot_str   = exam.slot_name or "–"

        story.append(Paragraph(
            f"{course_code} &nbsp;|&nbsp; {group_name} &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; {slot_str}",
            S["subtitle"],
        ))

        student_exams = exam.studentexam_set.select_related(
            "student__user", "room"
        ).order_by("student__reg_no")

        if not student_exams.exists():
            story.append(Paragraph("No students assigned.", S["cell"]))
            story.append(Spacer(1, 0.2 * cm))
            continue

        s_headers = ["Reg No", "Student Name", "Room", "Sign In", "Sign Out", "Status"]
        s_data    = [[Paragraph(h, S["header_cell"]) for h in s_headers]]

        for se in student_exams:
            full_name = (
                f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                if se.student and se.student.user else "–"
            )
            reg_no   = se.student.reg_no if se.student else "–"
            room_name = se.room.name     if se.room    else "–"
            sign_in   = se.signin_attendance.strftime("%H:%M")  if se.signin_attendance  else "–"
            sign_out  = se.signout_attendance.strftime("%H:%M") if se.signout_attendance else "–"

            status_style = (
                S["badge_active"] if se.status == "present"
                else S["badge_inactive"]
            )
            s_data.append([
                Paragraph(reg_no,    S["cell"]),
                Paragraph(full_name, S["cell"]),
                Paragraph(room_name, S["cell_center"]),
                Paragraph(sign_in,   S["cell_center"]),
                Paragraph(sign_out,  S["cell_center"]),
                Paragraph(se.status or "–", status_style),
            ])

        s_tbl = Table(
            s_data,
            colWidths=["15%", "30%", "15%", "13%", "13%", "14%"],
            repeatRows=1,
        )
        s_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), SECONDARY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_ODD, ROW_EVEN]),
            ("BOX",            (0, 0), (-1, -1), 0.8, BORDER),
            ("INNERGRID",      (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ]))
        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4 * cm))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ── View ──────────────────────────────────────────────────────────────────────
class TimetablePDFView(generics.GenericAPIView):
    """
    GET /timetable/pdf/?id=<timetable_id>

    Mirrors the logic of your existing list() view:
      - ?id=<n>   → PDF for that specific MasterTimetable
      - no id     → PDF for the most recent MasterTimetable
    """

    authentication_classes = []   # TODO: restore auth before going to production
    permission_classes     = []

    def get(self, request, *args, **kwargs):
        timetable_id = request.GET.get("id")

        # ── Resolve MasterTimetable ───────────────────────────────────────────
        if timetable_id:
            try:
                timetable_id = int(timetable_id)
            except ValueError:
                return Response(
                    {"success": False,
                     "message": "Invalid timetable ID (must be an integer)."},
                    status=400,
                )
            timetable = MasterTimetable.objects.filter(pk=timetable_id).first()
            if not timetable:
                return Response(
                    {"success": False,
                     "message": f"No MasterTimetable found with ID {timetable_id}."},
                    status=404,
                )
        else:
            timetable = MasterTimetable.objects.order_by("-created_at").first()
            if not timetable:
                return Response(
                    {"success": False,
                     "message": "No timetables exist yet."},
                    status=404,
                )

        # ── Filter exams for this timetable ───────────────────────────────────
        exams = Exam.objects.filter(
            mastertimetableexam__master_timetable_id=timetable.id
        ).distinct()

        if not exams.exists():
            return Response(
                {"success": True,
                 "data": [],
                 "message": f"No exams found for timetable ID {timetable.id}."},
            )

        # ── Build PDF ─────────────────────────────────────────────────────────
        try:
            pdf_bytes = _build_exam_timetable_pdf(timetable, exams)
        except Exception as exc:
            return Response(
                {"success": False, "message": f"PDF generation failed: {exc}"},
                status=500,
            )

        filename = f"exam_timetable_{timetable.id}_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response