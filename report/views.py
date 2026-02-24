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
from schedules.models import MasterTimetable    
import datetime

# ── Font Registration ─────────────────────────────────────────────────────────
#
#   fonts/GOTHIC.TTF    → Century Gothic Regular   (required)
#   fonts/GOTHICB.TTF   → Century Gothic Bold      (required)
#   fonts/GOTHICI.TTF   → Century Gothic Italic    (optional)
#   fonts/GOTHICBI.TTF  → Century Gothic Bold Italic (optional)

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Logo path — place your university logo here
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.jpeg")


def _register_century_gothic() -> tuple:
    alias_reg      = "centurygothic"
    alias_bold     = "centurygothic_bold"
    alias_italic   = "centurygothic"
    alias_bold_ita = "centurygothic"

    reg_path      = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path     = os.path.join(FONT_DIR, "centurygothic_bold.ttf")
    italic_path   = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_ita_path = os.path.join(FONT_DIR, "centurygothic.ttf")

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


FONT_REGULAR, FONT_BOLD = _register_century_gothic()


# ── Colours ───────────────────────────────────────────────────────────────────
PRIMARY      = colors.HexColor("#004594")   # AUCA primary blue
BLUE_HEADER  = colors.HexColor("#004594")   # title banner
COL_HEADER   = colors.HexColor("#D9E1F2")   # tinted column header (light primary)
DAY_ROW      = colors.HexColor("#FFFFFF")
DATE_ROW     = colors.HexColor("#FFFFFF")
SPACER_ROW   = colors.HexColor("#B8CCE4")   # light-blue separator (tint of primary)
BORDER_COL   = colors.HexColor("#004594")   # border matches primary
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
    Returns story elements for the AUCA header:
      - Logo centered
      - University name centered below logo
      - Faculty line centered
      - Blue banner with timetable title
    """
    story = []

    # ── Logo + university name — all horizontally centered ───────────────────
    if os.path.isfile(LOGO_PATH):
        logo_img = Image(LOGO_PATH, width=2.5 * cm, height=2.5 * cm)
    else:
        logo_img = Paragraph("", _s("NoLogo"))

    header_data = [[logo_img],
                   [Paragraph("Adventist University of Central Africa",
                               _sb("UniName", fontSize=16, textColor=TEXT_DARK,
                                   alignment=TA_CENTER, leading=22))],
                   [Paragraph("P.O. Box 2461 Kigali, Rwanda  |  www.auca.ac.rw  |  info@auca.ac.rw",
                               _s("UniSub", fontSize=8, textColor=TEXT_DARK,
                                  alignment=TA_CENTER))]]

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

    # ── Faculty line ──────────────────────────────────────────────────────────
    story.append(Paragraph(
        timetable_name,
        _sb("Faculty", fontSize=13, alignment=TA_CENTER, textColor=TEXT_DARK),
    ))
    story.append(Spacer(1, 0.2 * cm))

    
    story.append(Spacer(1, 0.1 * cm))

    return story


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _dept_banner(dept_name: str, is_cross_listed: bool = False, associated_depts: list = None) -> Table:
    """
    Blue department separator banner — shows primary department and associated departments.
    """
    display_name = dept_name.upper()
    
    # Remove the "(Cross-listed)" suffix if present
    if display_name.endswith(" (CROSS-LISTED)"):
        display_name = display_name.replace(" (CROSS-LISTED)", "")
    
    # Add associated departments if this is a cross-listed section
    if is_cross_listed and associated_depts:
        dept_names = [d.name for d in associated_depts if d]
        if dept_names:
            display_name += f" (also: {', '.join(dept_names)})"
    
    data = [[Paragraph(
        display_name,
        _sb("DeptBanner", fontSize=11, textColor=TEXT_WHITE, alignment=TA_CENTER),
    )]]
    tbl = Table(data, colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLUE_HEADER),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _build_dept_table(dept_exams: list, is_cross_listed: bool = False) -> Table:
    """
    Build one exam table for a single department.
    Grouping: date → time slot → merge same-course rows (groups as A, B, C).
    """
    from collections import OrderedDict, defaultdict

    hdr  = _sb("TH",  fontSize=9, textColor=TEXT_DARK, alignment=TA_LEFT)
    cell = _s("TD",   fontSize=8, textColor=TEXT_DARK, alignment=TA_LEFT,   leading=11)
    celc = _s("TDC",  fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    
    # Configure columns based on whether this is cross-listed view
    if is_cross_listed:
        COL_W = [2.5*cm, 2.0*cm, 6.0*cm, 8.5*cm, 3.0*cm, 1.5*cm]
        headers = ["Day&Date", "Time", "Teacher", "Course", "Group", "Offered By"]
    else:
        COL_W = [2.5*cm, 2.0*cm, 6.0*cm, 8.5*cm, 3.5*cm]
        headers = ["Day&Date", "Time", "Teacher", "Course", "Group"]

    tbl_data = [[Paragraph(h, hdr) for h in headers]]
    
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0), COL_HEADER),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER_COL),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#93A8C8")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
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

            course_rows = OrderedDict()
            for exam in slot_exams:
                course = exam.group.course if exam.group else None
                c_id = course.id if course else 0
                
                merge_key = (c_id, time_key)  # Group by course AND time
                if merge_key not in course_rows:
                    course_rows[merge_key] = {
                        "course_title": course.title if course else "–",
                        "course_code": course.code if course else "–",
                        "groups": [],
                        "teachers": [],
                        "dept_code": course.department.code if course and course.department else "",
                    }
                if exam.group:
                    course_rows[merge_key]["groups"].append(exam.group.group_name)
                if exam.group and exam.group.instructor:
                    instructor_name = exam.group.instructor.get_full_name()
                    if instructor_name and instructor_name not in course_rows[merge_key]["teachers"]:
                        course_rows[merge_key]["teachers"].append(instructor_name)

            for slot_i, row_data in enumerate(course_rows.values()):
                teacher_str = ", ".join(sorted(set(row_data["teachers"]))) if row_data["teachers"] else ""
                groups_str = ", ".join(sorted(set(row_data["groups"]))) if row_data["groups"] else "–"

                if not date_shown and slot_i == 0:
                    day_cell_text = f"<b>{day_name}</b><br/>{date_str}"
                    date_shown = True
                elif slot_i == 0:
                    day_cell_text = date_str
                else:
                    day_cell_text = ""

                # Build course display with code
                course_display = f"<b>{row_data['course_code']}</b><br/>{row_data['course_title']}"

                row = [
                    Paragraph(day_cell_text, celc),
                    Paragraph(time_str if slot_i == 0 else "", celc),
                    Paragraph(teacher_str, cell),
                    Paragraph(course_display, cell),
                    Paragraph(groups_str, celc),
                ]
                
                # Add department code for cross-listed view
                if is_cross_listed:
                    row.append(Paragraph(row_data['dept_code'], celc))
                
                tbl_data.append(row)
                row_idx += 1

        # Separator row after each date block
        sep_row = [Paragraph("", cell)] * (len(headers))
        tbl_data.append(sep_row)
        style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), SPACER_ROW))
        style_cmds.append(("ROWHEIGHT", (0, row_idx), (-1, row_idx), 8))
        row_idx += 1

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 1 — EXAM TIMETABLE grouped by DEPARTMENT
# ═══════════════════════════════════════════════════════════════════════════════
def _build_timetable_pdf(timetable: MasterTimetable, exams) -> bytes:
    """
    Landscape A4 timetable grouped by Department.
    Now handles cross-departmental courses properly.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
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
            "date",
            "start_time",
            "group__course__title",
            "group__group_name",
        )
    )

    # ── Group exams by primary department, but include cross-departmental courses ──
    from collections import defaultdict
    
    # Track which departments each course belongs to
    course_dept_map = {}
    for exam in exams:
        if exam.group and exam.group.course:
            course = exam.group.course
            if course.id not in course_dept_map:
                # Get primary department and all associated departments
                primary_dept = course.department
                associated = list(course.associated_departments.all())
                course_dept_map[course.id] = {
                    'primary': primary_dept,
                    'all': [primary_dept] + associated if associated else [primary_dept],
                    'is_cross': course.is_cross_departmental
                }
    
    # Group exams by each department they belong to
    by_dept = defaultdict(list)
    processed_for_primary = set()  # Track which exams we've added to primary departments
    
    for exam in exams:
        if exam.group and exam.group.course:
            course = exam.group.course
            dept_info = course_dept_map.get(course.id, {})
            
            # Add exam under primary department (always)
            if dept_info.get('primary'):
                primary_dept_name = dept_info['primary'].name
                by_dept[primary_dept_name].append(exam)
                processed_for_primary.add(exam.id)
            
            # Also add under associated departments if cross-departmental
            if dept_info.get('is_cross', False):
                for dept in dept_info.get('all', [])[1:]:  # Skip primary, take associated
                    if dept:
                        # Create a reference for cross-listed view with associated depts info
                        by_dept[f"{dept.name} (Cross-listed)"].append({
                            'exam': exam,
                            'primary_dept': dept_info['primary'],
                            'associated_depts': dept_info['all'][1:]  # All except primary
                        })
        else:
            # Fallback for exams without proper course association
            by_dept["No Department"].append(exam)

    # ── Assemble story ────────────────────────────────────────────────────────
    faculty_name = getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    timetable_lbl = f"Campus: {timetable.location.name.capitalize()}, Academic year: {timetable.academic_year}, Semester: {timetable.semester.name.capitalize()} ({timetable.category.capitalize()})"

    story = _logo_and_header(timetable_lbl, faculty_name)

    # Track processed courses to avoid duplication in display
    processed_exam_ids = set()
    has_cross_listed = False

    for dept_name in sorted(by_dept.keys()):
        dept_items = by_dept[dept_name]
        is_cross_listed = dept_name.endswith("(Cross-listed)")
        
        # Extract exams and associated info for this department
        dept_exams = []
        associated_depts = None
        
        for item in dept_items:
            if is_cross_listed:
                # Item is a dict with exam and dept info
                exam = item['exam']
                if exam.id not in processed_exam_ids:  # Still track to avoid duplicates in tables
                    dept_exams.append(exam)
                if not associated_depts:
                    associated_depts = item.get('associated_depts', [])
            else:
                # Item is just an exam
                exam = item
                if exam.id not in processed_exam_ids:
                    dept_exams.append(exam)
                    processed_exam_ids.add(exam.id)
        
        if not dept_exams:
            continue
            
        if is_cross_listed:
            has_cross_listed = True
            
        # Department banner with cross-listed info
        story.append(Spacer(1, 0.3 * cm))
        story.append(_dept_banner(dept_name, is_cross_listed, associated_depts))
        story.append(Spacer(1, 0.1 * cm))

        # Department exam table (without extra column)
        story.append(_build_dept_table(dept_exams, is_cross_listed))

    # Add footnote if there are cross-listed courses
    if has_cross_listed:
        story.append(Spacer(1, 0.3 * cm))
        story.append(HRFlowable(
            width="100%", thickness=0.5, color=colors.grey,
            spaceBefore=2, spaceAfter=2
        ))
        story.append(Paragraph(
            "† Cross-listed courses appear in multiple department sections.",
            _s("Footnote", fontSize=7, textColor=colors.grey, alignment=TA_LEFT)
        ))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
 
def _build_seating_pdf(
    timetable: MasterTimetable,
    student_exams,
    room_id=None,
    date=None,
    start_time=None,
    end_time=None
) -> bytes:
    import datetime as dt
    from collections import OrderedDict

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Seating Report – {timetable.id}",
    )

    # ── Apply filters directly on StudentExam ─────────────────────────────────
    if room_id:
        student_exams = student_exams.filter(room_id=room_id)

    if date:
        student_exams = student_exams.filter(exam__date=date)

    if start_time and end_time:
        student_exams = student_exams.filter(
            exam__start_time=start_time,
            exam__end_time=end_time,
        )

    # ── Styles ────────────────────────────────────────────────────────────────
    hdr           = _sb("SH",         fontSize=9,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=12)
    cell          = _s("SC",          fontSize=8,  textColor=TEXT_DARK,   alignment=TA_LEFT,   leading=11)
    celc          = _s("SCC",         fontSize=8,  textColor=TEXT_DARK,   alignment=TA_CENTER, leading=11)
    exam_title_s  = _sb("ExTitle",    fontSize=11, textColor=BLUE_HEADER, spaceBefore=12, spaceAfter=6, leading=14)
    room_header_s = _sb("RoomHeader", fontSize=10, textColor=PRIMARY,     alignment=TA_LEFT, spaceBefore=8, spaceAfter=4)

    faculty_name  = getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    timetable_lbl = f"Campus: {timetable.location.name.capitalize()}, Academic year: {timetable.academic_year}, Semester: {timetable.semester.name.capitalize()}"

    # ── Build report title ────────────────────────────────────────────────────
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

    # ── No data found ─────────────────────────────────────────────────────────
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
            _s("NoData", fontSize=12, alignment=TA_CENTER, textColor=colors.grey)
        ))
        doc.build(story, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()

    # ── Summary banner ────────────────────────────────────────────────────────
    if room_id and date and start_time and end_time:
        story.append(Paragraph(
            f"<b>SLOT REPORT – {format_time(str(start_time))} to {format_time(str(end_time))}</b>",
            _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER)
        ))
        story.append(Spacer(1, 0.2 * cm))
    elif room_id and date:
        story.append(Paragraph(
            f"<b>FULL DAY REPORT</b>",
            _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER)
        ))
        story.append(Spacer(1, 0.2 * cm))

    # ── Group by (room, date, start_time, end_time) ───────────────────────────
    slot_groups = OrderedDict()
    for se in student_exams:
        room_name = se.room.name if se.room else "No Room"
        key = (room_name, se.exam.date, se.exam.start_time, se.exam.end_time)
        if key not in slot_groups:
            slot_groups[key] = []
        slot_groups[key].append(se)

    current_room = None

    for (room_name, slot_date, slot_start, slot_end), slot_student_exams in slot_groups.items():

        # Room separator for full timetable reports
        if not room_id:
            if room_name != current_room:
                if current_room is not None:
                    story.append(Spacer(1, 0.4 * cm))
                    story.append(HRFlowable(
                        width="100%", thickness=1, color=PRIMARY,
                        spaceBefore=2, spaceAfter=2
                    ))
                current_room = room_name
                story.append(Paragraph(
                    f"ROOM: {room_name.upper()}",
                    room_header_s
                ))
                story.append(Spacer(1, 0.1 * cm))

        # ── Slot header ───────────────────────────────────────────────────────
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

        # ── Column config ─────────────────────────────────────────────────────
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

        # ── Table style ───────────────────────────────────────────────────────
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
            table_style.extend([
                ("BACKGROUND", (4, 0), (5, 0), colors.HexColor("#E6F0FA")),
            ])

        s_tbl = Table(s_data, colWidths=col_widths, repeatRows=1)
        s_tbl.setStyle(TableStyle(table_style))

        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4 * cm))

        if room_id:
            story.append(Paragraph(
                "<i>Note: Students must sign in before exam and sign out after completion.</i>",
                _s("Note", fontSize=7, textColor=colors.grey, alignment=TA_RIGHT)
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
            mastertimetableexam__master_timetable_id=timetable.id, master_timetable=timetable
        ).all()

        if not exams.exists():
            return Response({
                "success": True,
                "data": [],
                "message": f"No exams found for timetable ID {timetable.id}.",
            })

        report_type = request.GET.get("report", "timetable").lower()
        room_id = request.GET.get("room_id")
        date = request.GET.get("date")
        start_time = request.GET.get("start_time")
        end_time = request.GET.get("end_time")

        if room_id:
            try:
                room_id = int(room_id)
            except ValueError:
                return Response({
                    "success": False,
                    "message": "Invalid room ID — must be an integer."
                }, status=400)

        try:
            if report_type == "seating":
                # ── Use StudentExam as base queryset, not Exam ─────────────────
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
                    end_time=end_time
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
                filename = f"exam_timetable_{timetable.id}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"

        except Exception as exc:
            return Response(
                {"success": False, "message": f"PDF generation failed: {exc}"},
                status=500,
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response