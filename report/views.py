from rest_framework import generics
from rest_framework.response import Response
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
    KeepTogether,
    Image,
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
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
LOGO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "logo.jpeg"
)


def _register_century_gothic() -> tuple:
    alias_reg = "centurygothic"
    alias_bold = "centurygothic_bold"
    alias_italic = "centurygothic"
    alias_bold_ita = "centurygothic"

    reg_path = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_path = os.path.join(FONT_DIR, "centurygothic_bold.ttf")
    italic_path = os.path.join(FONT_DIR, "centurygothic.ttf")
    bold_ita_path = os.path.join(FONT_DIR, "centurygothic.ttf")

    for label, path in [
        ("Regular  → centurygothic.ttf", reg_path),
        ("Bold     → centurygothic_bold.ttf", bold_path),
    ]:
        if not os.path.isfile(path):
            raise RuntimeError(
                f"Century Gothic {label} not found.\n" f"Expected location: {path}"
            )

    pdfmetrics.registerFont(TTFont(alias_reg, reg_path))
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
        italic=alias_italic if alias_italic in registered else alias_reg,
        boldItalic=alias_bold_ita if alias_bold_ita in registered else alias_bold,
    )
    return alias_reg, alias_bold


FONT_REGULAR, FONT_BOLD = _register_century_gothic()


# ── Colours ───────────────────────────────────────────────────────────────────
PRIMARY = colors.HexColor("#3467A1")
BLUE_HEADER = colors.HexColor("#2168B9")
COL_HEADER = colors.HexColor("#D9E1F2")
DAY_ROW = colors.HexColor("#FFFFFF")
DATE_ROW = colors.HexColor("#FFFFFF")
DAY_SEP_COL = colors.HexColor("#F4B183")  # salmon stripe between days (matches PDF)
SPACER_ROW = colors.HexColor("#B8CCE4")  # kept — imported by attendance_views
CROSS_TINT = colors.HexColor("#FFF3E0")  # kept — imported by attendance_views
CROSS_BADGE = "#E29C55"  # kept — imported by attendance_views
BORDER_COL = colors.HexColor("#216ABD")
TEXT_DARK = colors.HexColor("#000000")
TEXT_WHITE = colors.HexColor("#FFFFFF")
SLOT_SEP_COL = colors.HexColor("#F4B183")


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
        self.drawString(
            1.5 * cm,
            0.8 * cm,
            f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        )
        self.drawRightString(
            w - 1.5 * cm, 0.8 * cm, f"Page {self._pageNumber} of {total}"
        )
        self.restoreState()


# ── Style helpers ─────────────────────────────────────────────────────────────
def _s(name, **kwargs):
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"], fontName=FONT_REGULAR, **kwargs)


def _sb(name, **kwargs):
    base = getSampleStyleSheet()
    return ParagraphStyle(name, parent=base["Normal"], fontName=FONT_BOLD, **kwargs)


def _logo_and_header(timetable_name: str, faculty: str) -> list:
    story = []

    # Logo
    if os.path.isfile(LOGO_PATH):
        logo_img = Image(LOGO_PATH, width=3 * cm, height=3 * cm)
    else:
        logo_img = Paragraph("", _s("NoLogo"))

    # Text block
    text_block = [
        [
            Paragraph(
                "Adventist University of Central Africa",
                _sb(
                    "UniName",
                    fontSize=16,
                    textColor=PRIMARY,
                    alignment=TA_LEFT,
                    leading=18,
                ),
            )
        ],
        [
            Paragraph(
                "P.O. Box 2461 Kigali, Rwanda  |  www.auca.ac.rw  |  info@auca.ac.rw",
                _s(
                    "UniSub",
                    fontSize=8,
                    textColor=TEXT_DARK,
                    alignment=TA_LEFT,
                ),
            )
        ],
    ]

    text_table = Table(text_block)
    text_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    # Main header (side-by-side)
    header_tbl = Table(
        [[logo_img, text_table]],
        colWidths=[3.2 * cm, None],
    )

    header_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "LEFT"),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story.append(header_tbl)
    story.append(Spacer(1, 0.25 * cm))

    story.append(Spacer(1, 0.15 * cm))

    # Banner
    banner_tbl = Table(
        [
            [
                Paragraph(
                    timetable_name,
                    _sb(
                        "Banner",
                        fontSize=10,
                        textColor=TEXT_WHITE,
                        alignment=TA_CENTER,
                    ),
                )
            ]
        ],
        colWidths=["100%"],
    )

    banner_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    story.append(banner_tbl)
    story.append(Spacer(1, 0.2 * cm))

    return story


_WEEK_ORDINALS = {1: "FIRST", 2: "SECOND", 3: "THIRD", 4: "FOURTH", 5: "FIFTH"}


def _week_label(week_num: int) -> str:
    word = _WEEK_ORDINALS.get(week_num, f"{week_num}TH")
    return f"{word} WEEK"


def _build_flat_timetable_table(exams: list) -> Table:

    hdr_s = _sb("TH", fontSize=9, textColor=TEXT_DARK, alignment=TA_CENTER)
    day_s = _sb("DAY", fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER, leading=12)
    celc = _s("TDC", fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    cell = _s("TD", fontSize=8, textColor=TEXT_DARK, alignment=TA_LEFT, leading=11)
    week_s = _sb("WEEK", fontSize=9, textColor=TEXT_WHITE, alignment=TA_CENTER)

    # Separator colours
    SLOT_SEP_COL = colors.HexColor(
        "#F4B183"
    )  # amber-orange  → between slots within a day
    # DAY_SEP_COL (salmon) already defined globally → between days
    # SPACER_ROW  (light blue) already defined globally → between days (alt style)

    COL_W = [2.5 * cm, 1.8 * cm, 5.4 * cm, 6.0 * cm, 2.3 * cm]
    HEADERS = ["Day & Date", "Time", "Teacher", "Course", "Group"]

    tbl_data = [[Paragraph(h, hdr_s) for h in HEADERS]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COL_HEADER),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, BORDER_COL),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#000000")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#000000")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    # ── Deduplicate ──────────────────────────────────────────────────────────
    seen_ids = set()
    unique_exams = []
    for exam in exams:
        if exam.id not in seen_ids:
            seen_ids.add(exam.id)
            unique_exams.append(exam)

    # ── Group by date ─────────────────────────────────────────────────────────
    by_date = defaultdict(list)
    for exam in unique_exams:
        by_date[exam.date or "No Date"].append(exam)

    sorted_dates = sorted(
        by_date.keys(),
        key=lambda d: (
            d if isinstance(d, datetime.date) else datetime.date(9999, 12, 31)
        ),
    )

    row_idx = 1
    first_day = True
    current_week = None
    week_counter = 0

    for date_key in sorted_dates:

        # ── Week banner ───────────────────────────────────────────────────────
        if isinstance(date_key, datetime.date):
            iso_week = date_key.isocalendar()[1]
        else:
            iso_week = None

        if iso_week is not None and iso_week != current_week:
            week_counter += 1

            if not first_day:
                # Light-blue day separator before week banner
                tbl_data.append([""] * 5)
                style_cmds += [
                    ("SPAN", (0, row_idx), (-1, row_idx)),
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), SPACER_ROW),
                    ("ROWHEIGHT", (0, row_idx), (-1, row_idx), 6),
                    ("TOPPADDING", (0, row_idx), (-1, row_idx), 0),
                    ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 0),
                ]
                row_idx += 1

            # Week banner row
            tbl_data.append(
                [
                    Paragraph(_week_label(week_counter), week_s),
                    "",
                    "",
                    "",
                    "",
                ]
            )
            style_cmds += [
                ("SPAN", (0, row_idx), (-1, row_idx)),
                ("BACKGROUND", (0, row_idx), (-1, row_idx), PRIMARY),
                ("ROWHEIGHT", (0, row_idx), (-1, row_idx), 18),
                ("TOPPADDING", (0, row_idx), (-1, row_idx), 4),
                ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 4),
            ]
            row_idx += 1
            current_week = iso_week
            first_day = True

        # ── Light-blue separator between days (within same week) ──────────────
        if not first_day:
            tbl_data.append([""] * 5)
            style_cmds += [
                ("SPAN", (0, row_idx), (-1, row_idx)),
                ("BACKGROUND", (0, row_idx), (-1, row_idx), SPACER_ROW),
                ("ROWHEIGHT", (0, row_idx), (-1, row_idx), 6),
                ("TOPPADDING", (0, row_idx), (-1, row_idx), 0),
                ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 0),
            ]
            row_idx += 1
        first_day = False

        # ── Group exams by time slot ──────────────────────────────────────────
        by_time = defaultdict(list)
        for exam in by_date[date_key]:
            by_time[exam.start_time].append(exam)

        sorted_times = sorted(
            by_time.keys(),
            key=lambda t: t if t else datetime.time(23, 59),
        )

        # Build slot blocks (list of course rows per slot)
        slot_blocks = []
        for time_key in sorted_times:
            time_str = time_key.strftime("%I:%M%p").lstrip("0") if time_key else "–"

            course_map = OrderedDict()
            for exam in by_time[time_key]:
                course = exam.group.course if exam.group else None
                c_id = course.id if course else 0
                if c_id not in course_map:
                    course_map[c_id] = {
                        "course_title": course.title if course else "–",
                        "course_code": course.code if course else "–",
                        "groups": [],
                        "teachers": [],
                    }
                if exam.group:
                    g = exam.group.group_name
                    if g and g not in course_map[c_id]["groups"]:
                        course_map[c_id]["groups"].append(g)
                if exam.group and exam.group.instructor:
                    name = exam.group.instructor.get_full_name()
                    if name and name not in course_map[c_id]["teachers"]:
                        course_map[c_id]["teachers"].append(name)

            slot_rows = []
            for row in course_map.values():
                teacher_str = ", ".join(row["teachers"]) if row["teachers"] else ""
                groups_str = ", ".join(sorted(row["groups"])) if row["groups"] else "–"
                course_disp = f"<b>{row['course_code']}</b> {row['course_title']}"
                slot_rows.append(
                    {
                        "time_str": time_str,
                        "teacher": teacher_str,
                        "course": course_disp,
                        "groups": groups_str,
                    }
                )
            slot_blocks.append(slot_rows)

        # ── Day&Date label ────────────────────────────────────────────────────
        try:
            day_name = date_key.strftime("%A")
            date_str = f"{date_key.day}-{date_key.strftime('%b')}"
            day_cell_text = f"<b>{day_name}</b><br/>{date_str}"
        except AttributeError:
            day_cell_text = str(date_key)

        day_span_start = row_idx
        first_data_row = True
        total_data_rows = 0

        # ── Emit slots with amber separators between them ─────────────────────
        for s_idx, slot_rows in enumerate(slot_blocks):

            # Amber-orange separator BETWEEN slots (not before the first)
            if s_idx > 0:
                tbl_data.append([""] * 5)
                style_cmds += [
                    ("SPAN", (1, row_idx), (-1, row_idx)),
                    ("BACKGROUND", (1, row_idx), (-1, row_idx), SLOT_SEP_COL),
                    ("ROWHEIGHT", (1, row_idx), (-1, row_idx), 5),
                    ("TOPPADDING", (1, row_idx), (-1, row_idx), 0),
                    ("BOTTOMPADDING", (1, row_idx), (-1, row_idx), 0),
                ]
                row_idx += 1  # separator row — NOT counted in total_data_rows

            # ── Time cell spans all data rows of this slot ────────────────────
            slot_start_row = row_idx
            slot_row_count = len(slot_rows)

            for course_idx, dr in enumerate(slot_rows):
                tbl_data.append(
                    [
                        Paragraph(day_cell_text if first_data_row else "", day_s),
                        # Time shown only in first row of slot; spanned below
                        Paragraph(dr["time_str"] if course_idx == 0 else "", celc),
                        Paragraph(dr["teacher"], cell),
                        Paragraph(dr["course"], cell),
                        Paragraph(dr["groups"], celc),
                    ]
                )
                first_data_row = False
                total_data_rows += 1
                row_idx += 1

            # ROWSPAN the Time cell (col 1) across all rows of this slot
            if slot_row_count > 1:
                style_cmds.append(
                    (
                        "SPAN",
                        (1, slot_start_row),
                        (1, slot_start_row + slot_row_count - 1),
                    )
                )

        # ROWSPAN the Day&Date cell (col 0) across all real data rows of this day
        span_end = row_idx - 1
        if span_end > day_span_start:
            style_cmds.append(("SPAN", (0, day_span_start), (0, span_end)))

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 1 — EXAM TIMETABLE
# ═══════════════════════════════════════════════════════════════════════════════


def _build_timetable_pdf(timetable: MasterTimetable, exams) -> bytes:
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title=f"Exam Timetable – {timetable.id}",
    )

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

    # ── Title label: EXACTLY as original code — not changed ──────────────────
    timetable_lbl = (
        f"Campus: {timetable.location.name.capitalize()}, "
        f"Academic year: {timetable.academic_year}, "
        f"Semester: {timetable.semester.name.capitalize()} "
        f"({timetable.category.capitalize()})"
    )

    story = _logo_and_header(timetable_lbl, "")
    story.append(_build_flat_timetable_table(exams))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
#  REPORT 2 — STUDENT SEATING  (original — untouched)
# ═══════════════════════════════════════════════════════════════════════════════
def _build_seating_pdf(
    timetable: MasterTimetable,
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
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
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

    hdr = _sb("SH", fontSize=9, textColor=TEXT_DARK, alignment=TA_CENTER, leading=12)
    cell = _s("SC", fontSize=8, textColor=TEXT_DARK, alignment=TA_LEFT, leading=11)
    celc = _s("SCC", fontSize=8, textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    exam_title_s = _sb(
        "ExTitle",
        fontSize=11,
        textColor=BLUE_HEADER,
        spaceBefore=12,
        spaceAfter=6,
        leading=14,
    )
    room_header_s = _sb(
        "RoomHeader",
        fontSize=10,
        textColor=PRIMARY,
        alignment=TA_LEFT,
        spaceBefore=8,
        spaceAfter=4,
    )

    faculty_name = (
        getattr(timetable, "faculty", None) or "Faculty of Information Technology"
    )
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
            formatted_date = dt.datetime.strptime(str(date), "%Y-%m-%d").strftime(
                "%d %b %Y"
            )
        except Exception:
            formatted_date = str(date)
        report_title += f" - Date: {formatted_date}"
    if start_time and end_time:
        report_title += (
            f" - Time: {format_time(str(start_time))} to {format_time(str(end_time))}"
        )

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
        story.append(
            Paragraph(
                error_msg,
                _s("NoData", fontSize=12, alignment=TA_CENTER, textColor=colors.grey),
            )
        )
        doc.build(story, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()

    if room_id and date and start_time and end_time:
        story.append(
            Paragraph(
                f"<b>SLOT REPORT – {format_time(str(start_time))} to {format_time(str(end_time))}</b>",
                _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER),
            )
        )
        story.append(Spacer(1, 0.2 * cm))
    elif room_id and date:
        story.append(
            Paragraph(
                f"<b>FULL DAY REPORT</b>",
                _sb("Summary", fontSize=10, textColor=PRIMARY, alignment=TA_CENTER),
            )
        )
        story.append(Spacer(1, 0.2 * cm))

    slot_groups = OrderedDict()
    for se in student_exams:
        room_name = se.room.name if se.room else "No Room"
        key = (room_name, se.exam.date, se.exam.start_time, se.exam.end_time)
        if key not in slot_groups:
            slot_groups[key] = []
        slot_groups[key].append(se)

    current_room = None

    for (
        room_name,
        slot_date,
        slot_start,
        slot_end,
    ), slot_student_exams in slot_groups.items():

        if not room_id:
            if room_name != current_room:
                if current_room is not None:
                    story.append(Spacer(1, 0.4 * cm))
                    story.append(
                        HRFlowable(
                            width="100%",
                            thickness=1,
                            color=PRIMARY,
                            spaceBefore=2,
                            spaceAfter=2,
                        )
                    )
                current_room = room_name
                story.append(Paragraph(f"ROOM: {room_name.upper()}", room_header_s))
                story.append(Spacer(1, 0.1 * cm))

        date_str = slot_date.strftime("%d %b %Y") if slot_date else "–"
        time_str = slot_start.strftime("%I:%M %p").lstrip("0") if slot_start else "–"
        end_time_str = slot_end.strftime("%I:%M %p").lstrip("0") if slot_end else "–"

        seen_courses = {}
        for se in slot_student_exams:
            if se.exam.id not in seen_courses:
                title = (
                    se.exam.group.course.title
                    if se.exam.group and se.exam.group.course
                    else "–"
                )
                group_name = se.exam.group.group_name if se.exam.group else "–"
                seen_courses[se.exam.id] = f"{title} (Group {group_name})"
        courses_str = " | ".join(seen_courses.values())

        story.append(
            Paragraph(
                f"<b>{courses_str}</b><br/>{date_str} | {time_str} – {end_time_str}",
                exam_title_s,
            )
        )

        if room_id:
            headers = [
                "#",
                "Reg No",
                "Student Name",
                "Course",
                "Signature (In)",
                "Signature (Out)",
            ]
            col_widths = [0.8 * cm, 2.5 * cm, 5.0 * cm, 4.5 * cm, 3.0 * cm, 3.0 * cm]
        else:
            headers = ["#", "Reg No", "Student Name", "Course", "Room"]
            col_widths = [0.8 * cm, 2.5 * cm, 5.0 * cm, 4.5 * cm, 3.0 * cm]

        s_data = [[Paragraph(h, hdr) for h in headers]]

        for idx, se in enumerate(slot_student_exams, start=1):
            full_name = (
                f"{se.student.user.first_name} {se.student.user.last_name}".strip()
                if se.student and se.student.user
                else "–"
            )
            reg_no = se.student.reg_no if se.student else "–"
            course_title = (
                se.exam.group.course.title
                if se.exam and se.exam.group and se.exam.group.course
                else "–"
            )

            if room_id:
                s_data.append(
                    [
                        Paragraph(str(idx), celc),
                        Paragraph(reg_no, cell),
                        Paragraph(full_name, cell),
                        Paragraph(course_title, cell),
                        Paragraph("___________________", celc),
                        Paragraph("___________________", celc),
                    ]
                )
            else:
                s_room = se.room.name if se.room else "–"
                s_data.append(
                    [
                        Paragraph(str(idx), celc),
                        Paragraph(reg_no, cell),
                        Paragraph(full_name, cell),
                        Paragraph(course_title, cell),
                        Paragraph(s_room, celc),
                    ]
                )

        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), COL_HEADER),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#F8F9FC")],
            ),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#000000")),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#000000")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]
        if room_id:
            table_style.extend(
                [
                    ("BACKGROUND", (4, 0), (5, 0), colors.HexColor("#E6F0FA")),
                ]
            )

        s_tbl = Table(s_data, colWidths=col_widths, repeatRows=1)
        s_tbl.setStyle(TableStyle(table_style))

        story.append(KeepTogether(s_tbl))
        story.append(Spacer(1, 0.4 * cm))

        if room_id:
            story.append(
                Paragraph(
                    "<i>Note: Students must sign in before exam and sign out after completion.</i>",
                    _s("Note", fontSize=7, textColor=colors.grey, alignment=TA_RIGHT),
                )
            )
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
#  VIEWS  (original — untouched)
# ══════════════════════════════════════════════════════════════════════════════
class TimetablePDFView(generics.GenericAPIView):
    """
    GET /api/report/?id=<timetable_id>&report=timetable   → Exam timetable PDF
    GET /api/report/?id=<timetable_id>&report=seating     → Student seating PDF

    ?report defaults to 'timetable' if omitted.
    ?id defaults to the most recent MasterTimetable if omitted.
    """

    authentication_classes = []  # TODO: restore before going to production
    permission_classes = []

    def _resolve_timetable(self, request):
        """Return (timetable, error_response). One of them will be None."""
        timetable_id = request.GET.get("id")

        if timetable_id:
            try:
                timetable_id = int(timetable_id)
            except ValueError:
                return None, Response(
                    {
                        "success": False,
                        "message": "Invalid timetable ID — must be an integer.",
                    },
                    status=400,
                )
            timetable = MasterTimetable.objects.filter(pk=timetable_id).first()
            if not timetable:
                return None, Response(
                    {
                        "success": False,
                        "message": f"No MasterTimetable found with ID {timetable_id}.",
                    },
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
            return Response(
                {
                    "success": True,
                    "data": [],
                    "message": f"No exams found for timetable ID {timetable.id}.",
                }
            )

        report_type = request.GET.get("report", "timetable").lower()
        room_id = request.GET.get("room_id")
        date = request.GET.get("date")
        start_time = request.GET.get("start_time")
        end_time = request.GET.get("end_time")

        if room_id:
            try:
                room_id = int(room_id)
            except ValueError:
                return Response(
                    {
                        "success": False,
                        "message": "Invalid room ID — must be an integer.",
                    },
                    status=400,
                )

        try:
            if report_type == "seating":
                student_exams = (
                    StudentExam.objects.filter(
                        exam__mastertimetableexam__master_timetable_id=timetable.id
                    )
                    .select_related(
                        "student__user",
                        "room",
                        "exam",
                        "exam__group",
                        "exam__group__course",
                    )
                    .order_by("exam__date", "exam__start_time", "student__reg_no")
                )

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
