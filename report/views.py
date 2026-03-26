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
from collections import defaultdict, OrderedDict

from exams.models import Exam, StudentExam
from schedules.models import MasterTimetable
import datetime

# ── Font Registration ─────────────────────────────────────────────────────────
FONT_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.jpeg")


def _register_century_gothic() -> tuple:
    alias_reg  = "centurygothic"
    alias_bold = "centurygothic_bold"

    reg_path  = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path = os.path.join(FONT_DIR, "centurygothic_bold.ttf")

    for label, path in [("Regular", reg_path), ("Bold", bold_path)]:
        if not os.path.isfile(path):
            raise RuntimeError(
                f"Century Gothic {label} not found.\nExpected: {path}"
            )

    pdfmetrics.registerFont(TTFont(alias_reg,  reg_path))
    pdfmetrics.registerFont(TTFont(alias_bold, bold_path))

    registered = pdfmetrics.getRegisteredFontNames()
    registerFontFamily(
        alias_reg,
        normal=alias_reg,
        bold=alias_bold,
        italic=alias_reg,
        boldItalic=alias_bold,
    )
    return alias_reg, alias_bold


FONT_REGULAR, FONT_BOLD = _register_century_gothic()


# ── Colours ───────────────────────────────────────────────────────────────────
PRIMARY      = colors.HexColor("#3467A1")   # blue — day-banner rows
BLUE_HEADER  = colors.HexColor("#2168B9")   # table column header bg
COL_HEADER   = colors.HexColor("#D9E1F2")   # light blue header cells
AMBER_SLOT   = colors.HexColor("#E29C55")   # orange-amber time-slot separator
AMBER_LIGHT  = colors.HexColor("#FFF3E0")   # very light amber tint (slot rows)
BORDER_COL   = colors.HexColor("#216ABD")
TEXT_DARK    = colors.HexColor("#000000")
TEXT_WHITE   = colors.HexColor("#FFFFFF")
ROW_ALT      = colors.HexColor("#F5F8FF")   # subtle alternating row tint


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
def _s(name, **kw):
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"], fontName=FONT_REGULAR, **kw)


def _sb(name, **kw):
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"], fontName=FONT_BOLD, **kw)


# ── Logo / header block ───────────────────────────────────────────────────────
def _logo_and_header(timetable_name: str, faculty: str) -> list:
    story = []

    if os.path.isfile(LOGO_PATH):
        logo_img = Image(LOGO_PATH, width=2.5 * cm, height=2.5 * cm)
    else:
        logo_img = Paragraph("", _s("NoLogo"))

    header_data = [
        [logo_img],
        [Paragraph("Adventist University of Central Africa",
                   _sb("UniName", fontSize=16, textColor=TEXT_DARK,
                       alignment=TA_CENTER, leading=22))],
        [Paragraph("P.O. Box 2461 Kigali, Rwanda  |  www.auca.ac.rw  |  info@auca.ac.rw",
                   _s("UniSub", fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER))],
    ]
    header_tbl = Table(header_data, colWidths=["100%"])
    header_tbl.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (0, 0),   4),
        ("BOTTOMPADDING", (0, 0), (0, 0),   6),
        ("TOPPADDING",    (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.25 * cm))

    # Faculty name
    story.append(Paragraph(
        faculty,
        _sb("FacTitle", fontSize=14, alignment=TA_CENTER, textColor=TEXT_DARK),
    ))
    story.append(Spacer(1, 0.15 * cm))

    # Blue banner: timetable label
    banner_data = [[Paragraph(
        timetable_name,
        _sb("Banner", fontSize=12, textColor=TEXT_WHITE, alignment=TA_CENTER),
    )]]
    banner_tbl = Table(banner_data, colWidths=["100%"])
    banner_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PRIMARY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(banner_tbl)
    story.append(Spacer(1, 0.2 * cm))

    return story


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE TIMETABLE TABLE  (flat — no department grouping, no duplicates)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_flat_timetable_table(exams: list) -> Table:
    """
    Single flat table that mirrors the PDF design:

    • Column headers row  — light-blue background
    • DAY banner rows     — PRIMARY blue background, white bold text
    • Time-slot rows      — white background, exam data
    • Slot separator rows — thin AMBER_SLOT coloured stripe between time slots

    Cross-departmental courses appear ONCE only (first department alphabetically).
    Courses at the same date+time are merged into one row (groups concatenated).
    """

    hdr  = _sb("TH",  fontSize=9,  textColor=TEXT_DARK,  alignment=TA_CENTER)
    celc = _s("TDC",  fontSize=8,  textColor=TEXT_DARK,  alignment=TA_CENTER, leading=11)
    cell = _s("TD",   fontSize=8,  textColor=TEXT_DARK,  alignment=TA_LEFT,   leading=11)
    day_s = _sb("DAY", fontSize=9, textColor=TEXT_WHITE, alignment=TA_LEFT)

    # Portrait A4 usable width ≈ 18 cm  (21 – 1.5 – 1.5)
    # Day&Date | Time | Teacher | Course | Group
    COL_W   = [2.6*cm, 1.8*cm, 5.5*cm, 5.8*cm, 2.3*cm]
    HEADERS = ["Day&Date", "Time", "Teacher", "Course", "Group"]

    tbl_data   = [[Paragraph(h, hdr) for h in HEADERS]]
    style_cmds = [
        # Column header row
        ("BACKGROUND",    (0, 0), (-1, 0), COL_HEADER),
        ("FONTNAME",      (0, 0), (-1, 0), FONT_BOLD),
        ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
        # Global
        ("BOX",           (0, 0), (-1, -1), 0.6, BORDER_COL),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#AABFDC")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]

    # ── Deduplicate cross-dept courses: keep only the primary (FK) department ──
    # We track seen exam PKs so each physical exam row is added exactly once.
    seen_exam_ids = set()
    unique_exams  = []
    for exam in exams:
        if exam.id not in seen_exam_ids:
            seen_exam_ids.add(exam.id)
            unique_exams.append(exam)

    # ── Group by date ─────────────────────────────────────────────────────────
    by_date = defaultdict(list)
    for exam in unique_exams:
        by_date[exam.date or "No Date"].append(exam)

    row_idx = 1   # 0 = header

    for date_key in sorted(by_date.keys(),
                           key=lambda d: d if d != "No Date" else datetime.date(9999, 12, 31)):
        # ── DAY BANNER ROW ────────────────────────────────────────────────────
        try:
            day_name = date_key.strftime("%A")
            date_str = f"{date_key.day}-{date_key.strftime('%b')}"
            day_label = f"{day_name}   {date_str}"
        except AttributeError:
            day_label = str(date_key)

        # Span all 5 columns for the day banner
        tbl_data.append([
            Paragraph(day_label, day_s),
            Paragraph("", day_s),
            Paragraph("", day_s),
            Paragraph("", day_s),
            Paragraph("", day_s),
        ])
        style_cmds += [
            ("BACKGROUND",    (0, row_idx), (-1, row_idx), PRIMARY),
            ("SPAN",          (0, row_idx), (-1, row_idx)),
            ("ROWHEIGHT",     (0, row_idx), (-1, row_idx), 16),
            ("TOPPADDING",    (0, row_idx), (-1, row_idx), 4),
            ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 4),
        ]
        row_idx += 1

        # ── Group exams by time slot ──────────────────────────────────────────
        by_time = defaultdict(list)
        for exam in by_date[date_key]:
            by_time[exam.start_time].append(exam)

        sorted_times = sorted(by_time.keys(),
                              key=lambda t: t if t else datetime.time(23, 59))

        for t_idx, time_key in enumerate(sorted_times):
            slot_exams = by_time[time_key]
            time_str   = time_key.strftime("%I:%M%p").lstrip("0") if time_key else "–"

            # ── Merge same course (same course id) within this slot ───────────
            course_rows = OrderedDict()
            for exam in slot_exams:
                course    = exam.group.course if exam.group else None
                c_id      = course.id if course else 0
                merge_key = c_id

                if merge_key not in course_rows:
                    course_rows[merge_key] = {
                        "course_title": course.title if course else "–",
                        "course_code":  course.code  if course else "–",
                        "groups":    [],
                        "teachers":  [],
                    }
                if exam.group:
                    g = exam.group.group_name
                    if g and g not in course_rows[merge_key]["groups"]:
                        course_rows[merge_key]["groups"].append(g)
                if exam.group and exam.group.instructor:
                    name = exam.group.instructor.get_full_name()
                    if name and name not in course_rows[merge_key]["teachers"]:
                        course_rows[merge_key]["teachers"].append(name)

            # ── Emit one table row per merged course ──────────────────────────
            for slot_i, row_data in enumerate(course_rows.values()):
                teacher_str = ", ".join(row_data["teachers"]) if row_data["teachers"] else "–"
                groups_str  = ", ".join(sorted(row_data["groups"])) if row_data["groups"] else "–"
                course_disp = (
                    f"<b>{row_data['course_code']}</b>  {row_data['course_title']}"
                )

                # Show time only on the first sub-row of this slot
                t_cell = Paragraph(time_str if slot_i == 0 else "", celc)

                tbl_data.append([
                    Paragraph("", celc),          # Day&Date — blank (day banner above)
                    t_cell,
                    Paragraph(teacher_str, cell),
                    Paragraph(course_disp,  cell),
                    Paragraph(groups_str,  celc),
                ])
                row_idx += 1

            # ── Thin amber separator between time slots ───────────────────────
            if t_idx < len(sorted_times) - 1:
                tbl_data.append([Paragraph("", celc)] * 5)
                style_cmds += [
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), AMBER_SLOT),
                    ("ROWHEIGHT",  (0, row_idx), (-1, row_idx), 4),
                    ("TOPPADDING",    (0, row_idx), (-1, row_idx), 0),
                    ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 0),
                ]
                row_idx += 1

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 1 — EXAM TIMETABLE  (flat, portrait A4, matches PDF design)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_timetable_pdf(timetable, exams) -> bytes:
    """
    Portrait A4 timetable — one flat table, no department duplication.
    Design mirrors the uploaded PDF reference.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Exam Timetable – {timetable.id}",
    )

    # ── Fetch & order exams ───────────────────────────────────────────────────
    exams = list(
        exams.select_related(
            "group",
            "group__course",
            "group__course__department",
            "group__instructor",
            "room",
        ).order_by(
            "date",
            "start_time",
            "group__course__title",
            "group__group_name",
        )
    )

    # ── Build labels ──────────────────────────────────────────────────────────
    faculty_name = (
        getattr(timetable, "faculty", None)
        or "Faculty of Information Technology"
    )

    # Header banner text
    # e.g. "FINAL MID-SEM EXAM TIMETABLE  2025-2026(2)"
    category_upper = timetable.category.upper() if timetable.category else "MID-SEM"
    timetable_banner = (
        f"FINAL {category_upper} EXAM TIMETABLE\n"
        f"{timetable.academic_year}"
        + (f"({timetable.semester.name})" if timetable.semester else "")
    )

    # Sub-label (campus / location line shown inside header)
    location_label = (
        f"Campus: {timetable.location.name.capitalize()}"
        if timetable.location else ""
    )

    story = _logo_and_header(timetable_banner, faculty_name)

    if location_label:
        story.append(Paragraph(
            location_label,
            _s("LocLabel", fontSize=9, alignment=TA_CENTER, textColor=colors.grey),
        ))
        story.append(Spacer(1, 0.15 * cm))

    story.append(_build_flat_timetable_table(exams))

    # ── Footer contact line (matches PDF: email / EO name / phone) ────────────
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(
        width="100%", thickness=0.5, color=colors.grey,
        spaceBefore=2, spaceAfter=4,
    ))
    story.append(Paragraph(
        "Email: it.examoffice@auca.ac.rw  |  EO &amp; AR",
        _s("FooterContact", fontSize=8, alignment=TA_CENTER, textColor=colors.grey),
    ))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 2 — STUDENT SEATING  (original — untouched)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_seating_pdf(
    timetable,
    student_exams,
    room_id=None,
    date=None,
    start_time=None,
    end_time=None,
) -> bytes:
    import datetime as dt

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Seating Report – {timetable.id}",
    )

    if room_id:
        student_exams = student_exams.filter(room_id=room_id)
    if date:
        student_exams = student_exams.filter(exam__date=date)
    if start_time and end_time:
        student_exams = student_exams.filter(
            exam__start_time=start_time,
            exam__end_time=end_time,
        )

    hdr           = _sb("SH",         fontSize=9,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=12)
    cell          = _s("SC",          fontSize=8,  textColor=TEXT_DARK,   alignment=TA_LEFT,   leading=11)
    celc          = _s("SCC",         fontSize=8,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=11)
    exam_title_s  = _sb("ExTitle",    fontSize=11, textColor=BLUE_HEADER, spaceBefore=12, spaceAfter=6, leading=14)
    room_header_s = _sb("RoomHeader", fontSize=10, textColor=PRIMARY,     alignment=TA_LEFT, spaceBefore=8, spaceAfter=4)

    faculty_name  = getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()}"
    )

    report_title = f"STUDENT SEATING REPORT – {timetable_lbl}"
    if room_id:
        first_se = student_exams.filter(room_id=room_id).select_related("room").first()
        if first_se and first_se.room:
            report_title += f" - Room: {first_se.room.name}"
        else:
            report_title += f" - Room ID: {room_id}"
    if date:
        try:
            formatted_date = dt.datetime.strptime(str(date), "%Y-%m-%d").strftime("%d %b %Y")
        except Exception:
            formatted_date = str(date)
        report_title += f" - Date: {formatted_date}"
    if start_time and end_time:
        report_title += f" - Time: {format_time(str(start_time))} to {format_time(str(end_time))}"

    story = _logo_and_header(report_title, faculty_name)

    if not student_exams.exists():
        error_msg = "No exams found"
        if room_id:
            error_msg += f" for Room ID: {room_id}"
        if date:
            error_msg += f" on {date}"
        if start_time and end_time:
            error_msg += f" at {start_time}–{end_time}"
        error_msg += " in this timetable."
        story.append(Paragraph(
            error_msg,
            _s("NoData", fontSize=12, alignment=TA_CENTER, textColor=colors.grey),
        ))
        doc.build(story, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()

    if room_id and date and start_time and end_time:
        story.append(Paragraph(
            f"<b>SLOT REPORT – {format_time(str(start_time))} to {format_time(str(end_time))}</b>",
            _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER),
        ))
        story.append(Spacer(1, 0.2 * cm))
    elif room_id and date:
        story.append(Paragraph(
            "<b>FULL DAY REPORT</b>",
            _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER),
        ))
        story.append(Spacer(1, 0.2 * cm))

    slot_groups = OrderedDict()
    for se in student_exams:
        room_name = se.room.name if se.room else "No Room"
        key = (room_name, se.exam.date, se.exam.start_time, se.exam.end_time)
        if key not in slot_groups:
            slot_groups[key] = []
        slot_groups[key].append(se)

    current_room = None

    for (room_name, slot_date, slot_start, slot_end), slot_student_exams in slot_groups.items():

        if not room_id:
            if room_name != current_room:
                if current_room is not None:
                    story.append(Spacer(1, 0.4 * cm))
                    story.append(HRFlowable(
                        width="100%", thickness=1, color=PRIMARY,
                        spaceBefore=2, spaceAfter=2,
                    ))
                current_room = room_name
                story.append(Paragraph(
                    f"ROOM: {room_name.upper()}",
                    room_header_s,
                ))
                story.append(Spacer(1, 0.1 * cm))

        date_str     = slot_date.strftime("%d %b %Y")              if slot_date  else "–"
        time_str     = slot_start.strftime("%I:%M %p").lstrip("0") if slot_start else "–"
        end_time_str = slot_end.strftime("%I:%M %p").lstrip("0")   if slot_end   else "–"

        seen_courses = {}
        for se in slot_student_exams:
            if se.exam.id not in seen_courses:
                title      = se.exam.group.course.title if se.exam.group and se.exam.group.course else "–"
                group_name = se.exam.group.group_name   if se.exam.group else "–"
                seen_courses[se.exam.id] = f"{title} (Group {group_name})"
        courses_str = " | ".join(seen_courses.values())

        story.append(Paragraph(
            f"<b>{courses_str}</b><br/>{date_str} | {time_str} – {end_time_str}",
            exam_title_s,
        ))

        if room_id:
            headers    = ["#", "Reg No", "Student Name", "Course", "Signature (In)", "Signature (Out)"]
            col_widths = [0.8*cm, 2.5*cm, 5.0*cm, 4.5*cm, 3.0*cm, 3.0*cm]
        else:
            headers    = ["#", "Reg No", "Student Name", "Course", "Room"]
            col_widths = [0.8*cm, 2.5*cm, 5.0*cm, 4.5*cm, 3.0*cm]

        s_data = [[Paragraph(h, hdr) for h in headers]]

        for idx, se in enumerate(slot_student_exams, start=1):
            full_name = (
                f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                if se.student and se.student.user else "–"
            )
            reg_no       = se.student.reg_no if se.student else "–"
            course_title = (
                se.exam.group.course.title
                if se.exam and se.exam.group and se.exam.group.course else "–"
            )

            if room_id:
                s_data.append([
                    Paragraph(str(idx), celc),
                    Paragraph(reg_no, cell),
                    Paragraph(full_name, cell),
                    Paragraph(course_title, cell),
                    Paragraph("___________________", celc),
                    Paragraph("___________________", celc),
                ])
            else:
                s_room = se.room.name if se.room else "–"
                s_data.append([
                    Paragraph(str(idx), celc),
                    Paragraph(reg_no, cell),
                    Paragraph(full_name, cell),
                    Paragraph(course_title, cell),
                    Paragraph(s_room, celc),
                ])

        table_style = [
            ("BACKGROUND",    (0, 0), (-1, 0), COL_HEADER),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FC")]),
            ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_COL),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ]
        if room_id:
            table_style.append(("BACKGROUND", (4, 0), (5, 0), colors.HexColor("#E6F0FA")))

        s_tbl = Table(s_data, colWidths=col_widths, repeatRows=1)
        s_tbl.setStyle(TableStyle(table_style))

        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4 * cm))

        if room_id:
            story.append(Paragraph(
                "<i>Note: Students must sign in before exam and sign out after completion.</i>",
                _s("Note", fontSize=7, textColor=colors.grey, alignment=TA_RIGHT),
            ))
            story.append(Spacer(1, 0.2 * cm))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


def format_time(time_str):
    import datetime as dt
    if not time_str:
        return ""
    try:
        time_obj = dt.datetime.strptime(time_str, "%H:%M:%S")
        return time_obj.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


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
            mastertimetableexam__master_timetable_id=timetable.id,
            master_timetable=timetable,
        ).all()

        if not exams.exists():
            return Response({
                "success": True,
                "data": [],
                "message": f"No exams found for timetable ID {timetable.id}.",
            })

        report_type = request.GET.get("report", "timetable").lower()
        room_id     = request.GET.get("room_id")
        date        = request.GET.get("date")
        start_time  = request.GET.get("start_time")
        end_time    = request.GET.get("end_time")

        if room_id:
            try:
                room_id = int(room_id)
            except ValueError:
                return Response({
                    "success": False,
                    "message": "Invalid room ID — must be an integer.",
                }, status=400)

        try:
            if report_type == "seating":
                student_exams = StudentExam.objects.filter(
                    exam__mastertimetableexam__master_timetable_id=timetable.id
                ).select_related(
                    "student__user",
                    "room",
                    "exam",
                    "exam__group",
                    "exam__group__course",
                ).order_by("exam__date", "exam__start_time", "student__reg_no")

                pdf_bytes = _build_seating_pdf(
                    timetable,
                    student_exams,
                    room_id=room_id,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                )

                if room_id:
                    if date and start_time and end_time:
                        filename = (
                            f"room{room_id}_slot_{date}_"
                            f"{start_time.replace(':','')}-{end_time.replace(':','')}.pdf"
                        )
                    elif date:
                        filename = f"room{room_id}_fullday_{date}.pdf"
                    else:
                        filename = f"room{room_id}_report_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
                else:
                    filename = f"seating_report_{timetable.id}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
            else:
                pdf_bytes = _build_timetable_pdf(timetable, exams)
                filename  = f"exam_timetable_{timetable.id}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"

        except Exception as exc:
            return Response(
                {"success": False, "message": f"PDF generation failed: {exc}"},
                status=500,
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response