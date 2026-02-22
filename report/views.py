from rest_framework import generics
from rest_framework.response import Response
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether, Image,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
import os
import io
from django.utils import timezone
from collections import defaultdict

from exams.models import Exam, StudentExam
from schedules.models import MasterTimetable   # adjust to your app name


# ── Font Registration ─────────────────────────────────────────────────────────
#
#   fonts/GOTHIC.TTF    → Century Gothic Regular   (required)
#   fonts/GOTHICB.TTF   → Century Gothic Bold      (required)
#   fonts/GOTHICI.TTF   → Century Gothic Italic    (optional)
#   fonts/GOTHICBI.TTF  → Century Gothic Bold Italic (optional)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Logo path — place your university logo here
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")


def _register_century_gothic() -> tuple:
    alias_reg      = "CenturyGothic"
    alias_bold     = "CenturyGothic-Bold"
    alias_italic   = "CenturyGothic-Italic"
    alias_bold_ita = "CenturyGothic-BoldItalic"

    reg_path      = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path     = os.path.join(FONT_DIR, "centurygothic_bold.ttf")
    italic_path   = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_ita_path = os.path.join(FONT_DIR, "centurygothic_bold.ttf")

    for label, path in [("Regular  → GOTHIC.TTF",  reg_path),
                         ("Bold     → GOTHICB.TTF", bold_path)]:
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


FONT_REGULAR, FONT_BOLD = _register_century_gothic()


# ── Colours (matching the image exactly) ──────────────────────────────────────
BLUE_HEADER  = colors.HexColor("#4472C4")   # blue title banner
COL_HEADER   = colors.HexColor("#D9D9D9")   # grey column header row
DAY_ROW      = colors.HexColor("#FFFFFF")   # day name row (white, bold)
DATE_ROW     = colors.HexColor("#FFFFFF")   # date row (white)
SPACER_ROW   = colors.HexColor("#F4B183")   # salmon/orange separator row
BORDER_COL   = colors.HexColor("#000000")   # table border
TEXT_DARK    = colors.HexColor("#000000")
TEXT_WHITE   = colors.HexColor("#FFFFFF")


# ── Numbered-page canvas ──────────────────────────────────────────────────────
class _NumberedCanvas(rl_canvas.Canvas):
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
        self.setFillColor(colors.grey)
        self.drawString(1.5 * cm, 0.8 * cm,
                        f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
        self.drawRightString(w - 1.5 * cm, 0.8 * cm,
                             f"Page {self._pageNumber} of {total}")
        self.restoreState()


# ── Style helpers ─────────────────────────────────────────────────────────────
def _s(name, **kwargs):
    """Shortcut to build a ParagraphStyle with Century Gothic."""
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"],
                          fontName=FONT_REGULAR, **kwargs)


def _sb(name, **kwargs):
    """Shortcut to build a BOLD Century Gothic ParagraphStyle."""
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"],
                          fontName=FONT_BOLD, **kwargs)


# ── Logo helper ───────────────────────────────────────────────────────────────
def _logo_and_header(timetable_name: str, faculty: str) -> list:
    """
    Returns story elements that reproduce the AUCA header:
      [logo + university name]
      Faculty of ...
      [blue banner: timetable title]
    """
    story = []

    # University logo + name side by side
    if os.path.isfile(LOGO_PATH):
        logo = Image(LOGO_PATH, width=2.2 * cm, height=2.2 * cm)
    else:
        logo = Paragraph("", _s("NoLogo"))

    uni_name_style = _sb("UniName", fontSize=16, textColor=TEXT_DARK,
                          alignment=TA_LEFT, leading=20)
    uni_sub_style  = _s("UniSub",  fontSize=8,  textColor=TEXT_DARK,
                         alignment=TA_LEFT)

    uni_block = [
        [
            logo,
            [
                Paragraph("Adventist University of Central Africa", uni_name_style),
                Paragraph("P.O. Box 2461 Kigali, Rwanda  |  www.auca.ac.rw  |  info@auca.ac.rw",
                          uni_sub_style),
            ],
        ]
    ]
    logo_tbl = Table(uni_block, colWidths=[2.5 * cm, None])
    logo_tbl.setStyle(TableStyle([
        ("VALIGN",  (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(logo_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # Faculty line
    story.append(Paragraph(
        faculty,
        _sb("Faculty", fontSize=13, alignment=TA_CENTER, textColor=TEXT_DARK)
    ))
    story.append(Spacer(1, 0.2 * cm))

    # Blue banner
    banner_data = [[Paragraph(
        timetable_name.upper(),
        _sb("Banner", fontSize=13, textColor=TEXT_WHITE, alignment=TA_CENTER)
    )]]
    banner_tbl = Table(banner_data, colWidths=["100%"])
    banner_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLUE_HEADER),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(banner_tbl)
    story.append(Spacer(1, 0.1 * cm))

    return story


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 1 — EXAM TIMETABLE  (matches the image format exactly)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_timetable_pdf(timetable: MasterTimetable, exams) -> bytes:
    """
    Landscape A4 timetable in the AUCA format:
      • Logo + university name header
      • Faculty + blue banner title
      • Table with columns: Day&Date | Time | Teacher | Course | Group
      • Rows grouped by date, with an orange separator row between date groups
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Exam Timetable – {timetable.id}",
    )

    exams = exams.select_related(
        "group", "group__course", "room",
    ).prefetch_related(
        "mastertimetableexam_set__instructor",
    ).order_by("date", "start_time", "group__group_name")

    # ── Column styles ─────────────────────────────────────────────────────────
    hdr  = _sb("TH",   fontSize=9,  textColor=TEXT_DARK, alignment=TA_LEFT)
    cell = _s("TD",    fontSize=8,  textColor=TEXT_DARK, alignment=TA_LEFT,  leading=11)
    celb = _sb("TDB",  fontSize=8,  textColor=TEXT_DARK, alignment=TA_LEFT,  leading=11)
    celc = _s("TDC",   fontSize=8,  textColor=TEXT_DARK, alignment=TA_CENTER,leading=11)
    celbc= _sb("TDBC", fontSize=8,  textColor=TEXT_DARK, alignment=TA_CENTER,leading=11)

    # Column widths: Day&Date | Time | Teacher | Course | Group
    COL_W = [3.2*cm, 2.2*cm, 6.5*cm, 8*cm, 4.5*cm]

    # ── Column header row ─────────────────────────────────────────────────────
    tbl_data = [[
        Paragraph("Day&amp;Date", hdr),
        Paragraph("Time",         hdr),
        Paragraph("Teacher",      hdr),
        Paragraph("Course",       hdr),
        Paragraph("Group",        hdr),
    ]]
    # Style commands list — we'll append per-row styles as we build
    style_cmds = [
        # Column header
        ("BACKGROUND",    (0, 0), (-1, 0), COL_HEADER),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_COL),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#AAAAAA")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]

    # ── Group exams by date ───────────────────────────────────────────────────
    by_date = defaultdict(list)
    for exam in exams:
        key = exam.date or "No Date"
        by_date[key].append(exam)

    row_idx = 1   # row 0 is header

    for date_key in sorted(by_date.keys(), key=lambda d: d if d != "No Date" else "9999"):
        date_exams = by_date[date_key]

        for i, exam in enumerate(date_exams):
            # Day name on first exam of the date group, blank on subsequent
            if i == 0:
                try:
                    day_name = date_key.strftime("%A")
                    date_str = date_key.strftime("%-d-%b")   # e.g. 27-Feb
                except AttributeError:
                    day_name = str(date_key)
                    date_str = ""
            else:
                day_name = ""
                date_str = ""

            # Teacher(s)
            instructors = exam.mastertimetableexam_set.values_list(
                "instructor__first_name", "instructor__last_name"
            )
            teacher_str = ", ".join(
                f"{fn} {ln}".strip() for fn, ln in instructors if fn or ln
            ) or "–"

            course_title = (
                exam.group.course.title if exam.group and exam.group.course else "–"
            )
            group_name = exam.group.group_name if exam.group else "–"
            time_str   = exam.start_time.strftime("%I:%M%p").lstrip("0") if exam.start_time else "–"

            # Day name row (bold, first of date) vs continuation row
            day_cell  = Paragraph(day_name,  celbc if i == 0 else celc)
            date_cell = Paragraph(date_str,  celc)

            tbl_data.append([
                # Day&Date merged into one cell as two lines
                Paragraph(
                    f"<b>{day_name}</b><br/>{date_str}" if i == 0 else date_str,
                    celc
                ),
                Paragraph(time_str,     celc),
                Paragraph(teacher_str,  cell),
                Paragraph(f"<b>{course_title}</b>", cell),
                Paragraph(group_name,   celc),
            ])

            # Bold day name row styling
            if i == 0 and day_name:
                style_cmds.append(("FONTNAME", (0, row_idx), (0, row_idx), FONT_BOLD))

            row_idx += 1

        # Orange separator row between date groups
        tbl_data.append([Paragraph("", cell)] * 5)
        style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), SPACER_ROW))
        style_cmds.append(("ROWHEIGHT",  (0, row_idx), (-1, row_idx), 6))
        row_idx += 1

    main_tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    main_tbl.setStyle(TableStyle(style_cmds))

    # ── Assemble story ────────────────────────────────────────────────────────
    faculty_name  = getattr(timetable, "faculty",  "Faculty of Information Technology")
    timetable_lbl = getattr(timetable, "name",     f"Exam Timetable ID {timetable.id}")

    story = _logo_and_header(timetable_lbl, faculty_name)
    story.append(main_tbl)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 2 — STUDENT SEATING REPORT  (separate PDF)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_seating_pdf(timetable: MasterTimetable, exams) -> bytes:
    """
    Portrait A4 seating report — one section per exam showing every student,
    their assigned room, sign-in/out times, and attendance status.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Seating Report – {timetable.id}",
    )

    exams = exams.select_related(
        "group", "group__course", "room",
    ).order_by("date", "start_time")

    # Styles
    hdr   = _sb("SH",  fontSize=8,  textColor=TEXT_DARK, alignment=TA_LEFT)
    cell  = _s("SC",   fontSize=8,  textColor=TEXT_DARK, alignment=TA_LEFT,   leading=11)
    celc  = _s("SCC",  fontSize=8,  textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    celbc = _sb("SCBC",fontSize=8,  textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    exam_title_s = _sb("ExTitle", fontSize=10, textColor=BLUE_HEADER,
                        spaceBefore=10, spaceAfter=4)

    faculty_name  = getattr(timetable, "faculty",  "Faculty of Information Technology")
    timetable_lbl = getattr(timetable, "name",     f"Exam Timetable ID {timetable.id}")

    story = _logo_and_header(
        f"STUDENT SEATING REPORT – {timetable_lbl}",
        faculty_name,
    )

    for exam in exams:
        course_title = (exam.group.course.title
                        if exam.group and exam.group.course else "–")
        group_name   = exam.group.group_name if exam.group else "–"
        room_name    = exam.room.name        if exam.room  else "–"
        date_str     = exam.date.strftime("%d %b %Y") if exam.date else "–"
        time_str     = exam.start_time.strftime("%I:%M %p").lstrip("0") if exam.start_time else "–"

        story.append(Paragraph(
            f"{course_title}  |  Group: {group_name}  |  {date_str}  |  {time_str}  |  Room: {room_name}",
            exam_title_s,
        ))

        student_exams = (
            StudentExam.objects
            .filter(exam=exam)
            .select_related("student__user", "room")
            .order_by("student__reg_no")
        )

        if not student_exams.exists():
            story.append(Paragraph("No students assigned to this exam.", cell))
            story.append(Spacer(1, 0.3 * cm))
            continue

        s_data = [[
            Paragraph(h, hdr)
            for h in ["#", "Reg No", "Student Name", "Room", "Sign In", "Sign Out", "Status"]
        ]]

        for idx, se in enumerate(student_exams, start=1):
            full_name = (
                f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                if se.student and se.student.user else "–"
            )
            reg_no    = se.student.reg_no if se.student else "–"
            s_room    = se.room.name if se.room else "–"
            sign_in   = se.signin_attendance.strftime("%H:%M")  if se.signin_attendance  else "–"
            sign_out  = se.signout_attendance.strftime("%H:%M") if se.signout_attendance else "–"
            status    = (se.status or "–").capitalize()

            s_data.append([
                Paragraph(str(idx),  celc),
                Paragraph(reg_no,    cell),
                Paragraph(full_name, cell),
                Paragraph(s_room,    celc),
                Paragraph(sign_in,   celc),
                Paragraph(sign_out,  celc),
                Paragraph(status,    celc),
            ])

        s_tbl = Table(
            s_data,
            colWidths=[1*cm, 2.8*cm, 5.5*cm, 2.8*cm, 2.2*cm, 2.2*cm, 2.2*cm],
            repeatRows=1,
        )
        s_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), COL_HEADER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#EBF5FB")]),
            ("BOX",            (0, 0), (-1, -1), 0.5, BORDER_COL),
            ("INNERGRID",      (0, 0), (-1, -1), 0.3, colors.HexColor("#AAAAAA")),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
        ]))
        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4 * cm))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
#  VIEWS
# ══════════════════════════════════════════════════════════════════════════════
class TimetablePDFView(generics.GenericAPIView):
    """
    GET /api/report/?id=<timetable_id>&report=timetable   → Exam timetable PDF
    GET /api/report/?id=<timetable_id>&report=seating     → Student seating PDF

    ?report defaults to 'timetable' if omitted.
    ?id defaults to the most recent MasterTimetable if omitted.
    """
    authentication_classes = []   # TODO: restore before going to production
    permission_classes     = []

    def _resolve_timetable(self, request):
        """Return (timetable, error_response). One of them will be None."""
        timetable_id = request.GET.get("id")

        if timetable_id:
            try:
                timetable_id = int(timetable_id)
            except ValueError:
                return None, Response(
                    {"success": False,
                     "message": "Invalid timetable ID — must be an integer."},
                    status=400,
                )
            timetable = MasterTimetable.objects.filter(pk=timetable_id).first()
            if not timetable:
                return None, Response(
                    {"success": False,
                     "message": f"No MasterTimetable found with ID {timetable_id}."},
                    status=404,
                )
        else:
            timetable = MasterTimetable.objects.order_by("-created_at").first()
            if not timetable:
                return None, Response(
                    {"success": False, "message": "No timetables exist yet."},
                    status=404,
                )

        return timetable, None

    def get(self, request, *args, **kwargs):
        timetable, err = self._resolve_timetable(request)
        if err:
            return err

        exams = Exam.objects.filter(
            mastertimetableexam__master_timetable_id=timetable.id
        ).distinct()

        if not exams.exists():
            return Response({
                "success": True,
                "data": [],
                "message": f"No exams found for timetable ID {timetable.id}.",
            })

        report_type = request.GET.get("report", "timetable").lower()

        try:
            if report_type == "seating":
                pdf_bytes = _build_seating_pdf(timetable, exams)
                filename  = f"seating_report_{timetable.id}_{timezone.now().strftime('%Y%m%d')}.pdf"
            else:
                pdf_bytes = _build_timetable_pdf(timetable, exams)
                filename  = f"exam_timetable_{timetable.id}_{timezone.now().strftime('%Y%m%d')}.pdf"
        except Exception as exc:
            return Response(
                {"success": False, "message": f"PDF generation failed: {exc}"},
                status=500,
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response