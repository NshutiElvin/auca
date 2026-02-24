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

# ── Font Registration ──────────────────────────────────────────────────────────
FONT_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.jpeg")


def _register_century_gothic() -> tuple:
    alias_reg  = "centurygothic"
    alias_bold = "centurygothic_bold"
    reg_path   = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path  = os.path.join(FONT_DIR, "centurygothic_bold.ttf")

    for label, path in [("Regular", reg_path), ("Bold", bold_path)]:
        if not os.path.isfile(path):
            raise RuntimeError(f"Century Gothic {label} not found at: {path}")

    pdfmetrics.registerFont(TTFont(alias_reg,  reg_path))
    pdfmetrics.registerFont(TTFont(alias_bold, bold_path))
    registerFontFamily(alias_reg, normal=alias_reg, bold=alias_bold,
                       italic=alias_reg, boldItalic=alias_bold)
    return alias_reg, alias_bold


FONT_REGULAR, FONT_BOLD = _register_century_gothic()

# ── Colours ────────────────────────────────────────────────────────────────────
PRIMARY     = colors.HexColor("#004594")
BLUE_HEADER = colors.HexColor("#004594")
COL_HEADER  = colors.HexColor("#D9E1F2")
SPACER_ROW  = colors.HexColor("#B8CCE4")
BORDER_COL  = colors.HexColor("#004594")
TEXT_DARK   = colors.HexColor("#000000")
TEXT_WHITE  = colors.HexColor("#FFFFFF")
CROSS_TINT  = colors.HexColor("#FFF3E0")   # warm amber tint for cross-listed rows
CROSS_BADGE = "#CC6600"                    # amber text for the badge


# ── Numbered-page canvas ───────────────────────────────────────────────────────
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


# ── Style helpers ──────────────────────────────────────────────────────────────
def _s(name, **kw):
    return ParagraphStyle(name, parent=getSampleStyleSheet()["Normal"],
                          fontName=FONT_REGULAR, **kw)

def _sb(name, **kw):
    return ParagraphStyle(name, parent=getSampleStyleSheet()["Normal"],
                          fontName=FONT_BOLD, **kw)


# ── Logo / header ──────────────────────────────────────────────────────────────
def _logo_and_header(timetable_name: str, faculty: str) -> list:
    story = []

    logo_img = (Image(LOGO_PATH, width=2.5*cm, height=2.5*cm)
                if os.path.isfile(LOGO_PATH) else Paragraph("", _s("_")))

    header_tbl = Table(
        [[logo_img],
         [Paragraph("Adventist University of Central Africa",
                    _sb("UN", fontSize=16, textColor=TEXT_DARK, alignment=TA_CENTER, leading=22))],
         [Paragraph("P.O. Box 2461 Kigali, Rwanda  |  www.auca.ac.rw  |  info@auca.ac.rw",
                    _s("US", fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER))]],
        colWidths=["100%"],
    )
    header_tbl.setStyle(TableStyle([
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        ("TOPPADDING",    (0,0), (0,0),   4),
        ("BOTTOMPADDING", (0,0), (0,0),   6),
        ("TOPPADDING",    (0,1), (-1,-1), 2),
        ("BOTTOMPADDING", (0,1), (-1,-1), 2),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph(timetable_name,
                           _sb("TL", fontSize=13, alignment=TA_CENTER, textColor=TEXT_DARK)))
    story.append(Spacer(1, 0.2*cm))
    return story


# ── Department banner ──────────────────────────────────────────────────────────
def _dept_banner(dept_name: str) -> Table:
    tbl = Table(
        [[Paragraph(dept_name.upper(),
                    _sb("DB", fontSize=11, textColor=TEXT_WHITE, alignment=TA_CENTER))]],
        colWidths=["100%"],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), BLUE_HEADER),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    return tbl


# ── Core table builder ─────────────────────────────────────────────────────────
def _build_dept_table(dept_exams: list) -> Table:
    """
    Builds one exam table for a single department section.

    Each exam in dept_exams may carry an optional attribute  `_cross_dept_codes`
    (a list of dept codes) injected by the caller to signal cross-listing.
    When present, the course cell gets a small amber badge and the row gets a
    warm tint so coordinators instantly see the duplication is intentional.

    Columns: Day & Date | Time | Teacher | Course | Group
    """
    hdr  = _sb("TH",  fontSize=9, textColor=TEXT_DARK, alignment=TA_LEFT)
    cell = _s("TD",   fontSize=8, textColor=TEXT_DARK, alignment=TA_LEFT,   leading=11)
    celc = _s("TDC",  fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)

    COL_W   = [2.5*cm, 2.0*cm, 6.0*cm, 9.5*cm, 3.5*cm]
    headers = ["Day & Date", "Time", "Teacher", "Course", "Group"]

    tbl_data   = [[Paragraph(h, hdr) for h in headers]]
    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0), COL_HEADER),
        ("BOX",           (0,0), (-1,-1), 0.5, BORDER_COL),
        ("INNERGRID",     (0,0), (-1,-1), 0.3, colors.HexColor("#93A8C8")),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
    ]

    by_date = defaultdict(list)
    for exam in dept_exams:
        by_date[exam.date or "No Date"].append(exam)

    row_idx = 1

    for date_key in sorted(by_date.keys(),
                           key=lambda d: d if d != "No Date" else "9999-99-99"):

        by_time = defaultdict(list)
        for exam in by_date[date_key]:
            by_time[exam.start_time].append(exam)

        try:
            day_name = date_key.strftime("%A")
            date_str = f"{date_key.day}-{date_key.strftime('%b')}"
        except AttributeError:
            day_name = str(date_key)
            date_str = ""

        date_shown = False

        for time_key in sorted(by_time.keys(),
                               key=lambda t: t if t else "99:99"):
            slot_exams = by_time[time_key]
            time_str   = time_key.strftime("%I:%M%p").lstrip("0") if time_key else "–"

            # Merge rows that share the same course in this time slot
            course_rows = OrderedDict()
            for exam in slot_exams:
                course      = exam.group.course if exam.group else None
                merge_key   = (course.id if course else 0, time_key)

                if merge_key not in course_rows:
                    # Collect cross-dept badge codes (injected by caller)
                    cross_codes = getattr(exam, "_cross_dept_codes", [])
                    course_rows[merge_key] = {
                        "course_title":  course.title if course else "–",
                        "course_code":   course.code  if course else "–",
                        "is_cross":      bool(cross_codes),
                        "cross_codes":   cross_codes,
                        "groups":        [],
                        "teachers":      [],
                    }

                if exam.group:
                    course_rows[merge_key]["groups"].append(exam.group.group_name)
                if exam.group and exam.group.instructor:
                    name = exam.group.instructor.get_full_name()
                    if name and name not in course_rows[merge_key]["teachers"]:
                        course_rows[merge_key]["teachers"].append(name)

            for slot_i, row_data in enumerate(course_rows.values()):
                teacher_str = ", ".join(sorted(set(row_data["teachers"]))) or "–"
                groups_str  = ", ".join(sorted(set(row_data["groups"])))  or "–"

                # Day cell: show full day+date only on first row of a new date block
                if not date_shown and slot_i == 0:
                    day_cell = f"<b>{day_name}</b><br/>{date_str}"
                    date_shown = True
                elif slot_i == 0:
                    day_cell = date_str
                else:
                    day_cell = ""

                # Course cell: code + title + optional cross-listed badge
                course_display = f"<b>{row_data['course_code']}</b>  {row_data['course_title']}"
                if row_data["is_cross"] and row_data["cross_codes"]:
                    badge = " | ".join(row_data["cross_codes"])
                    course_display += (
                        f'<br/><font size="7" color="{CROSS_BADGE}">'
                        f'&#10022; Cross-listed with: {badge}</font>'
                    )

                tbl_data.append([
                    Paragraph(day_cell,                             celc),
                    Paragraph(time_str if slot_i == 0 else "",      celc),
                    Paragraph(teacher_str,                          cell),
                    Paragraph(course_display,                       cell),
                    Paragraph(groups_str,                           celc),
                ])

                # Warm tint for cross-listed rows so they stand out immediately
                if row_data["is_cross"]:
                    style_cmds.append(
                        ("BACKGROUND", (0, row_idx), (-1, row_idx), CROSS_TINT)
                    )

                row_idx += 1

        # Thin separator row between date blocks
        tbl_data.append([Paragraph("", cell)] * len(headers))
        style_cmds += [
            ("BACKGROUND", (0, row_idx), (-1, row_idx), SPACER_ROW),
            ("ROWHEIGHT",  (0, row_idx), (-1, row_idx), 8),
        ]
        row_idx += 1

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 1 — EXAM TIMETABLE grouped by DEPARTMENT
# ═══════════════════════════════════════════════════════════════════════════════
def _build_timetable_pdf(timetable: "MasterTimetable", exams) -> bytes:
    """
    Landscape A4 exam timetable grouped by department.

    Cross-departmental courses appear under EVERY department they belong to
    (course.department  +  course.associated_departments).  Each duplicated
    row carries a small amber badge listing the other departments so readers
    immediately understand the intentional repetition.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.8*cm,
        title=f"Exam Timetable – {timetable.id}",
    )

    exams = list(
        exams.select_related(
            "group",
            "group__course",
            "group__course__department",
            "room",
        ).prefetch_related(
            "group__course__associated_departments"
        ).order_by(
            "group__course__department__name",
            "date", "start_time",
            "group__course__title",
            "group__group_name",
        )
    )

    # ── Build per-department exam buckets ──────────────────────────────────────
    #
    # by_dept  : { dept_name -> [exam, ...] }
    #
    # For cross-departmental courses we append the same exam object into every
    # relevant department bucket, but first we attach a transient attribute
    # `_cross_dept_codes` so _build_dept_table can render the badge without
    # needing to re-query the DB.
    #
    # We use a small wrapper to avoid mutating the real ORM object across
    # different buckets.

    class _ExamProxy:
        """Thin wrapper that forwards attribute access to the real exam but
        lets us attach extra data per-department view."""
        __slots__ = ("_exam", "_cross_dept_codes")

        def __init__(self, exam, cross_codes):
            object.__setattr__(self, "_exam", exam)
            object.__setattr__(self, "_cross_dept_codes", cross_codes)

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_exam"), name)

    by_dept = defaultdict(list)          # dept_name -> list of _ExamProxy
    has_cross = False

    for exam in exams:
        if not (exam.group and exam.group.course):
            # Exam has no course/group — slot under a catch-all bucket
            by_dept["No Department"].append(_ExamProxy(exam, []))
            continue

        course = exam.group.course

        # All departments this course belongs to
        fk_dept     = course.department                             # the FK dept
        assoc_depts = (list(course.associated_departments.all())
                       if course.is_cross_departmental else [])
        all_depts   = [fk_dept] + assoc_depts if fk_dept else assoc_depts

        if len(all_depts) > 1:
            has_cross = True

        for dept in all_depts:
            if not dept:
                continue
            # Badge lists the OTHER departments (not the one currently shown)
            other_codes = [d.code for d in all_depts if d and d.id != dept.id]
            by_dept[dept.name].append(_ExamProxy(exam, other_codes))

    # ── Assemble story ─────────────────────────────────────────────────────────
    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()} "
        f"({timetable.category.capitalize()})"
    )
    faculty_name = getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    story = _logo_and_header(timetable_lbl, faculty_name)

    for dept_name in sorted(by_dept.keys()):
        dept_exams = by_dept[dept_name]
        if not dept_exams:
            continue

        story.append(Spacer(1, 0.3*cm))
        story.append(_dept_banner(dept_name))
        story.append(Spacer(1, 0.1*cm))
        story.append(_build_dept_table(dept_exams))

    # ── Legend (only if cross-listed courses exist) ────────────────────────────
    if has_cross:
        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey,
                                spaceBefore=2, spaceAfter=4))
        story.append(Paragraph(
            f'<font color="{CROSS_BADGE}">&#10022; Cross-listed with: DEPT</font>'
            " — This course is also examined under the listed department(s). "
            "The exam row appears in each relevant department section.",
            _s("Legend", fontSize=7, textColor=colors.grey),
        ))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 2 — STUDENT SEATING (unchanged logic, preserved exactly)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_seating_pdf(
    timetable: "MasterTimetable",
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
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.8*cm,
        title=f"Seating Report – {timetable.id}",
    )

    if room_id:
        student_exams = student_exams.filter(room_id=room_id)
    if date:
        student_exams = student_exams.filter(exam__date=date)
    if start_time and end_time:
        student_exams = student_exams.filter(
            exam__start_time=start_time, exam__end_time=end_time)

    hdr           = _sb("SH",  fontSize=9,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=12)
    cell          = _s("SC",   fontSize=8,  textColor=TEXT_DARK,   alignment=TA_LEFT,   leading=11)
    celc          = _s("SCC",  fontSize=8,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=11)
    exam_title_s  = _sb("ET",  fontSize=11, textColor=BLUE_HEADER, spaceBefore=12, spaceAfter=6, leading=14)
    room_header_s = _sb("RH",  fontSize=10, textColor=PRIMARY,     alignment=TA_LEFT,   spaceBefore=8, spaceAfter=4)

    faculty_name  = getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()}"
    )

    report_title = f"STUDENT SEATING REPORT – {timetable_lbl}"
    if room_id:
        first_se = student_exams.select_related("room").first()
        report_title += f" - Room: {first_se.room.name}" if first_se and first_se.room else f" - Room ID: {room_id}"
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
        msg = "No exams found"
        if room_id:   msg += f" for Room ID: {room_id}"
        if date:      msg += f" on {date}"
        if start_time and end_time: msg += f" at {start_time}–{end_time}"
        msg += " in this timetable."
        story.append(Paragraph(msg, _s("ND", fontSize=12, alignment=TA_CENTER, textColor=colors.grey)))
        doc.build(story, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()

    if room_id and date and start_time and end_time:
        story.append(Paragraph(
            f"<b>SLOT REPORT – {format_time(str(start_time))} to {format_time(str(end_time))}</b>",
            _sb("Sum", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER)))
        story.append(Spacer(1, 0.2*cm))
    elif room_id and date:
        story.append(Paragraph("<b>FULL DAY REPORT</b>",
                               _sb("Sum2", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER)))
        story.append(Spacer(1, 0.2*cm))

    slot_groups = OrderedDict()
    for se in student_exams:
        key = (se.room.name if se.room else "No Room",
               se.exam.date, se.exam.start_time, se.exam.end_time)
        slot_groups.setdefault(key, []).append(se)

    current_room = None
    for (room_name, slot_date, slot_start, slot_end), ses in slot_groups.items():

        if not room_id:
            if room_name != current_room:
                if current_room is not None:
                    story.append(Spacer(1, 0.4*cm))
                    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY,
                                            spaceBefore=2, spaceAfter=2))
                current_room = room_name
                story.append(Paragraph(f"ROOM: {room_name.upper()}", room_header_s))
                story.append(Spacer(1, 0.1*cm))

        date_str     = slot_date.strftime("%d %b %Y")              if slot_date  else "–"
        time_str     = slot_start.strftime("%I:%M %p").lstrip("0") if slot_start else "–"
        end_time_str = slot_end.strftime("%I:%M %p").lstrip("0")   if slot_end   else "–"

        seen_courses = {}
        for se in ses:
            if se.exam.id not in seen_courses:
                title      = se.exam.group.course.title if se.exam.group and se.exam.group.course else "–"
                group_name = se.exam.group.group_name   if se.exam.group else "–"
                seen_courses[se.exam.id] = f"{title} (Group {group_name})"
        courses_str = " | ".join(seen_courses.values())

        story.append(Paragraph(
            f"<b>{courses_str}</b><br/>{date_str} | {time_str} – {end_time_str}",
            exam_title_s))

        if room_id:
            headers    = ["#", "Reg No", "Student Name", "Course", "Signature (In)", "Signature (Out)"]
            col_widths = [0.8*cm, 2.5*cm, 5.0*cm, 4.5*cm, 3.0*cm, 3.0*cm]
        else:
            headers    = ["#", "Reg No", "Student Name", "Course", "Room"]
            col_widths = [0.8*cm, 2.5*cm, 5.0*cm, 4.5*cm, 3.0*cm]

        s_data = [[Paragraph(h, hdr) for h in headers]]
        for idx, se in enumerate(ses, 1):
            full_name    = (f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                            if se.student and se.student.user else "–")
            reg_no       = se.student.reg_no if se.student else "–"
            course_title = (se.exam.group.course.title
                            if se.exam and se.exam.group and se.exam.group.course else "–")
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
                s_data.append([
                    Paragraph(str(idx), celc),
                    Paragraph(reg_no, cell),
                    Paragraph(full_name, cell),
                    Paragraph(course_title, cell),
                    Paragraph(se.room.name if se.room else "–", celc),
                ])

        table_style = [
            ("BACKGROUND",     (0,0), (-1,0), COL_HEADER),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8F9FC")]),
            ("BOX",            (0,0), (-1,-1), 0.5, BORDER_COL),
            ("INNERGRID",      (0,0), (-1,-1), 0.3, colors.HexColor("#CCCCCC")),
            ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN",          (0,0), (-1,-1), "CENTER"),
            ("TOPPADDING",     (0,0), (-1,-1), 6),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
            ("LEFTPADDING",    (0,0), (-1,-1), 5),
            ("RIGHTPADDING",   (0,0), (-1,-1), 5),
        ]
        if room_id:
            table_style.append(("BACKGROUND", (4,0), (5,0), colors.HexColor("#E6F0FA")))

        s_tbl = Table(s_data, colWidths=col_widths, repeatRows=1)
        s_tbl.setStyle(TableStyle(table_style))
        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4*cm))

        if room_id:
            story.append(Paragraph(
                "<i>Note: Students must sign in before exam and sign out after completion.</i>",
                _s("Note", fontSize=7, textColor=colors.grey, alignment=TA_RIGHT)))
            story.append(Spacer(1, 0.2*cm))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ── Utility ────────────────────────────────────────────────────────────────────
def format_time(time_str: str) -> str:
    import datetime as dt
    if not time_str:
        return ""
    try:
        return dt.datetime.strptime(time_str, "%H:%M:%S").strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


# ══════════════════════════════════════════════════════════════════════════════
#  VIEWS
# ══════════════════════════════════════════════════════════════════════════════
class TimetablePDFView(generics.GenericAPIView):
    """
    GET /api/report/?id=<timetable_id>&report=timetable   → Exam timetable PDF
    GET /api/report/?id=<timetable_id>&report=seating     → Student seating PDF
    """
    authentication_classes = []
    permission_classes     = []

    def _resolve_timetable(self, request):
        timetable_id = request.GET.get("id")
        if timetable_id:
            try:
                timetable_id = int(timetable_id)
            except ValueError:
                return None, Response(
                    {"success": False, "message": "Invalid timetable ID — must be an integer."},
                    status=400)
            timetable = MasterTimetable.objects.filter(pk=timetable_id).first()
            if not timetable:
                return None, Response(
                    {"success": False, "message": f"No MasterTimetable found with ID {timetable_id}."},
                    status=404)
        else:
            timetable = MasterTimetable.objects.order_by("-created_at").first()
            if not timetable:
                return None, Response(
                    {"success": False, "message": "No timetables exist yet."},
                    status=404)
        return timetable, None

    def get(self, request, *args, **kwargs):
        timetable, err = self._resolve_timetable(request)
        if err:
            return err

        exams = Exam.objects.filter(
            mastertimetableexam__master_timetable_id=timetable.id,
            master_timetable=timetable,
        )

        if not exams.exists():
            return Response({
                "success": True, "data": [],
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
                return Response({"success": False, "message": "Invalid room ID."}, status=400)

        try:
            if report_type == "seating":
                student_exams = StudentExam.objects.filter(
                    exam__mastertimetableexam__master_timetable_id=timetable.id
                ).select_related(
                    "student__user", "room",
                    "exam", "exam__group", "exam__group__course",
                ).order_by("exam__date", "exam__start_time", "student__reg_no")

                pdf_bytes = _build_seating_pdf(
                    timetable, student_exams,
                    room_id=room_id, date=date,
                    start_time=start_time, end_time=end_time,
                )

                if room_id:
                    if date and start_time and end_time:
                        filename = f"room{room_id}_slot_{date}_{start_time.replace(':','')}-{end_time.replace(':','')}.pdf"
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
                status=500)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response