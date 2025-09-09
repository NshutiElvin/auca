 # # Standard Library
# from collections import defaultdict, deque
# from datetime import datetime, time, timedelta
# from itertools import combinations
# import heapq
# import logging
# from pprint import pprint
# import random
# import copy  # Added explicitly (missing in original)

# # Django
# from django.db import transaction
# from django.db.models import Count, Sum
# from django.utils.timezone import now

# # Local Models
# from courses.models import Course, CourseGroup
# from enrollments.models import Enrollment
# from exams.models import Exam, StudentExam
# from rooms.models import Room
# from schedules.models import MasterTimetable
# from django.db.models import Min, Max
# from datetime import timedelta, time
# from collections import defaultdict
# from notifications.tasks import send_exam_data
# from collections import defaultdict
# from datetime import timedelta
# from django.db.models import Min, Max, Prefetch

# logger = logging.getLogger(__name__)
 

# SLOTS = [
#     ("Morning", time(8, 0), time(11, 0)),
#     ("Afternoon", time(13, 0), time(16, 0)),
#     ("Evening", time(17, 0), time(20, 0)),
# ]
# FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]
# NO_EXAM_DAYS = ["Saturday"]


 


# def get_exam_slots(start_date, end_date, max_slots=None):

#     date_slots = []
#     current_date = start_date

#     while current_date <= end_date:
#         weekday = current_date.strftime("%A")
#         if weekday not in NO_EXAM_DAYS:
#             slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS
#             for label, start, end in slots:
#                 date_slots.append((current_date, label, start, end))
#                 if max_slots and len(date_slots) >= max_slots:
#                     break
#         current_date += timedelta(days=1)

#     return date_slots





 



# def find_compatible_courses_within_group(courses):
#     if not courses:
#         return {"compatible_groups": [], "group_conflicts": defaultdict(list)}

#     # Get location and total capacity
#     location = Course.objects.filter(id=courses[0]).first().department.location.id
#     total_seats = (
#         Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))[
#             "total"
#         ]
#         or 0
#     )
#     max_students_per_timeslot = total_seats * 3

#     # Get all enrollments and organize data
#     course_students = defaultdict(set)
#     course_group_details = defaultdict(lambda: defaultdict(list))
#     course_group_students = defaultdict(lambda: defaultdict(set))
#     course_group_sizes = defaultdict(lambda: defaultdict(int))

#     for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
#         course_students[enrollment.course_id].add(enrollment.student_id)
#         course_group_details[enrollment.course_id][enrollment.group_id].append(
#             enrollment.student_id
#         )
#         course_group_students[enrollment.course_id][enrollment.group_id].add(
#             enrollment.student_id
#         )
#         course_group_sizes[enrollment.course_id][enrollment.group_id] += 1

#     # Find course conflicts (students taking multiple courses)
#     course_conflicts = defaultdict(list)
#     for course1, course2 in combinations(course_students.keys(), 2):
#         students1 = course_students[course1]
#         students2 = course_students[course2]

#         if students1 & students2:
#             course_conflicts[course1].append(course2)
#             course_conflicts[course2].append(course1)

#     # First attempt: try to schedule each course with all its groups together
#     color_courses = defaultdict(list)
#     color_student_counts = defaultdict(int)
#     color_course_groups = defaultdict(lambda: defaultdict(list))
#     colored = {}

#     course_list = sorted(
#         course_students.keys(),
#         key=lambda x: (-len(course_students[x]), -len(course_conflicts[x])),
#     )

#     for course in course_list:
#         course_student_count = len(course_students[course])
#         course_groups = list(course_group_students[course].keys())

#         available_colors = []
#         for color in range(len(course_students)):
#             # Check for conflicts
#             is_conflict_free = all(
#                 colored.get(conflict) != color
#                 for conflict in course_conflicts[course]
#                 if conflict in colored
#             )

#             # Check capacity
#             has_capacity = (
#                 color_student_counts[color] + course_student_count
#             ) <= max_students_per_timeslot

#             if is_conflict_free and has_capacity:
#                 available_colors.append(color)

#         if available_colors:
#             # Place entire course in the best color
#             chosen_color = min(available_colors, key=lambda c: color_student_counts[c])
#             colored[course] = chosen_color
#             color_courses[chosen_color].append(course)
#             color_student_counts[chosen_color] += course_student_count

#             # Record all groups for this course
#             for group_id in course_groups:
#                 color_course_groups[chosen_color][course].append(group_id)
#         else:
#             # Course doesn't fit entirely - need to split groups
#             # Sort groups by size (largest first) to optimize placement
#             sorted_groups = sorted(
#                 course_groups, key=lambda g: -course_group_sizes[course][g]
#             )
#             remaining_groups = sorted_groups.copy()

#             # Try to place as many groups as possible in adjacent timeslots
#             adjacent_colors = set()
#             placed_groups = []

#             # First pass: try to place groups in existing colors
#             for group_id in remaining_groups[:]:
#                 group_size = course_group_sizes[course][group_id]
#                 best_color = None
#                 min_remaining_capacity = float("inf")

#                 # Find the best color for this group
#                 for color in range(len(color_student_counts)):
#                     if any(
#                         colored.get(conflict) == color
#                         for conflict in course_conflicts[course]
#                         if conflict in colored
#                     ):
#                         continue

#                     remaining_capacity = (
#                         max_students_per_timeslot - color_student_counts[color]
#                     )
#                     if group_size <= remaining_capacity:
#                         if (
#                             best_color is None
#                             or remaining_capacity < min_remaining_capacity
#                         ):
#                             best_color = color
#                             min_remaining_capacity = remaining_capacity

#                 if best_color is not None:
#                     # Place group in best color
#                     color_course_groups[best_color][course].append(group_id)
#                     color_student_counts[best_color] += group_size
#                     placed_groups.append((group_id, best_color))
#                     adjacent_colors.add(best_color)
#                     remaining_groups.remove(group_id)

#             # Second pass: for remaining groups, try to place them adjacent to already placed groups
#             for group_id in remaining_groups[:]:
#                 group_size = course_group_sizes[course][group_id]

#                 # Try to place near existing groups of the same course
#                 if adjacent_colors:
#                     best_adjacent_color = None
#                     min_remaining_capacity = float("inf")

#                     for color in adjacent_colors:
#                         if any(
#                             colored.get(conflict) == color
#                             for conflict in course_conflicts[course]
#                             if conflict in colored
#                         ):
#                             continue

#                         remaining_capacity = (
#                             max_students_per_timeslot - color_student_counts[color]
#                         )
#                         if group_size <= remaining_capacity:
#                             if (
#                                 best_adjacent_color is None
#                                 or remaining_capacity < min_remaining_capacity
#                             ):
#                                 best_adjacent_color = color
#                                 min_remaining_capacity = remaining_capacity

#                     if best_adjacent_color is not None:
#                         color_course_groups[best_adjacent_color][course].append(
#                             group_id
#                         )
#                         color_student_counts[best_adjacent_color] += group_size
#                         placed_groups.append((group_id, best_adjacent_color))
#                         remaining_groups.remove(group_id)
#                         continue

#                 # If no adjacent slot available, create new color near existing ones
#                 if adjacent_colors:
#                     # Create new color with minimal distance from existing ones
#                     new_color = (
#                         max(adjacent_colors) + 1
#                         if max(adjacent_colors) + 1 not in adjacent_colors
#                         else min(adjacent_colors) - 1
#                     )
#                     if new_color < 0:
#                         new_color = max(adjacent_colors) + 1
#                 else:
#                     # No groups placed yet, create new color
#                     new_color = len(color_student_counts)

#                 # Initialize new color if needed
#                 if new_color not in color_student_counts:
#                     color_student_counts[new_color] = 0

#                 color_course_groups[new_color][course].append(group_id)
#                 color_student_counts[new_color] += group_size
#                 placed_groups.append((group_id, new_color))
#                 adjacent_colors.add(new_color)
#                 remaining_groups.remove(group_id)
 

#     # Convert to compatible groups format
#     compatible_groups = []
#     for color in sorted(color_course_groups.keys()):
#         courses_in_slot = []
#         total_students = 0

#         for course_id, group_ids in color_course_groups[color].items():
#             course_student_count = sum(
#                 course_group_sizes[course_id][group_id] for group_id in group_ids
#             )
#             total_students += course_student_count

#             courses_in_slot.append(
#                 {
#                     "course_id": course_id,
#                     "groups": group_ids,
#                     "student_count": course_student_count,
#                     "all_groups_scheduled_together": len(group_ids)
#                     == len(course_group_students[course_id]),
#                     "split_course": len(group_ids)
#                     < len(course_group_students[course_id]),
#                 }
#             )

#         compatible_groups.append(
#             {
#                 "timeslot": color + 1,
#                 "courses": courses_in_slot,
#                 "student_count": total_students,
#                 "within_capacity": total_students <= max_students_per_timeslot,
#             }
#         )

#     # Sort by timeslot number to maintain adjacency
#     compatible_groups.sort(key=lambda x: x["timeslot"])

#     return compatible_groups, course_conflicts

 


# def get_exam_time_for_group(
#     weekday, available_slots, available_seats=None, slots_usage=None, needed_steats=None
# ):

#     if weekday == "Saturday":
#         return None

#     for slot, number in slots_usage.items():
#         if number + needed_steats <= available_seats:
#             return slot
#     return None


# def fetch_courses(course_ids):
#     if course_ids:
#         return {c.id: c for c in Course.objects.filter(id__in=course_ids)}
#     # else fetch all courses with enrollments
#     courses_qs = Course.objects.annotate(enrollment_count=Count("enrollments")).filter(
#         enrollment_count__gt=0
#     )
#     return {c.id: c for c in courses_qs}


# def fetch_course_groups(group_ids):
#     return {g.id: g for g in CourseGroup.objects.filter(id__in=group_ids)}


# def get_slots_by_date(slots_input):
#     slots_by_date = {}
#     for date_str, value in slots_input.items():
#         date = datetime.strptime(date_str, "%Y-%m-%d").date()
#         slots_by_date[date] = value
#     return slots_by_date


# def prefetch_enrollments(course_groups):
#     course_group_ids = set()
#     for group in course_groups:
#         for course in group["courses"]:
#             course_group_ids.update(course["groups"])
#     enrollments_qs = (
#         Enrollment.objects.filter(group_id__in=course_group_ids)
#         .select_related("student")
#         .values("group_id", "student_id")
#     )
#     enrollments_by_group = defaultdict(list)
#     for enrollment in enrollments_qs:
#         enrollments_by_group[enrollment["group_id"]].append(enrollment["student_id"])
#     return enrollments_by_group


# def schedule_group_exams(
#     group_idx,
#     course_group,
#     current_date,
#     weekday,
#     slot_map,
#     all_slots,
#     all_available_seats,
#     courses_dict,
#     groups_dict,
#     enrollments_by_group,
#     master_timetable,
#     slot_seats_usage,
# ):

#     exams_created = []
#     unscheduled_reasons = {}
#     partially_scheduled = False

#     for course_idx, course_dict in enumerate(course_group["courses"]):
#         course_id = course_dict["course_id"]
#         if course_id not in courses_dict:
#             logger.warning(f"Course with id {course_id} not found")
#             continue

#         course = courses_dict[course_id]
#         remaining_groups = []
#         for group_id in course_dict["groups"]:
#             if group_id not in groups_dict:
#                 logger.warning(f"Group with id {group_id} not found")
#                 continue

#             group = groups_dict[group_id]
#             student_ids = enrollments_by_group.get(group_id, [])

#             if not student_ids:
#                 logger.info(f"No enrollments found for group {group_id}")
#                 unscheduled_reasons[group_id] = "No enrolled students"
#                 partially_scheduled = True
#                 continue
#             needed_seats = len(student_ids)
#             slot_name = get_exam_time_for_group(
#                 weekday, all_slots, all_available_seats, slot_seats_usage, needed_seats
#             )
#             print(slot_name)
#             if slot_name not in slot_map:
#                 reason = f"No valid time slot for group {group.group_name} on {weekday}"
#                 logger.info(reason)
#                 unscheduled_reasons[group_id] = reason
#                 partially_scheduled = True
#                 continue

#             wanted_slot = slot_map[slot_name]
#             start_time = time(*map(int, wanted_slot["start"].split(":")))
#             end_time = time(*map(int, wanted_slot["end"].split(":")))

#             if slot_seats_usage[slot_name] + needed_seats > all_available_seats:
#                 reason = (
#                     f"Not enough seats for course {course_id}, group {group_id} in {slot_name} slot "
#                     f"(Required: {needed_seats}, Available: {all_available_seats - slot_seats_usage[slot_name]})"
#                 )
#                 logger.info(reason)
#                 unscheduled_reasons[group_id] = reason
#                 partially_scheduled = True
#                 continue

#             try:
#                 exam = Exam.objects.create(
#                     date=current_date,
#                     start_time=start_time,
#                     end_time=end_time,
#                     group=group,
#                     slot_name=slot_name,
#                 )
#                 master_timetable.exams.add(exam)
#                 exams_created.append(exam)

#                 student_exam_objs = [
#                     StudentExam(student_id=student_id, exam=exam)
#                     for student_id in student_ids
#                 ]
#                 StudentExam.objects.bulk_create(student_exam_objs)

#                 slot_seats_usage[slot_name] += needed_seats
#                 logger.debug(
#                     f"Scheduled course {course_id}, group {group_id} at {start_time}–{end_time}"
#                 )

#             except Exception as e:
#                 logger.error(
#                     f"Failed to create exam for course {course_id}, group {group_id}: {e}"
#                 )
#                 unscheduled_reasons[group_id] = str(e)
#                 partially_scheduled = True
#                 remaining_groups.append(group_id)

#         # Update groups for this course to only those not scheduled
#         course_dict["groups"] = remaining_groups

#     # Clean courses with no groups left
#     course_group["courses"] = [c for c in course_group["courses"] if c["groups"]]

#     return exams_created, partially_scheduled, unscheduled_reasons


# def generate_exam_schedule(
#     slots=None, course_ids=None, master_timetable: MasterTimetable = None, location=None
# ):
#     try:
#         courses_dict = fetch_courses(course_ids)

#         enrolled_course_ids = list(courses_dict.keys())
#         compatible_groups, _ = find_compatible_courses_within_group(enrolled_course_ids)
#         pprint(compatible_groups)
#         unscheduled_reasons = {}

#         if not compatible_groups:
#             logger.info("No compatible course groups found")
#             return [], "No compatible course groups found", [], {}

#         slots_by_date = get_slots_by_date(slots)
#         dates = sorted(
#             date for date in slots_by_date if date.strftime("%A") != "Saturday"
#         )

#         if not dates:
#             logger.info("No available dates (excluding Saturdays)")
#             # populate unscheduled reasons for all groups
#             for group in compatible_groups:
#                 for course in group["courses"]:
#                     for group_id in course["groups"]:
#                         unscheduled_reasons[group_id] = (
#                             "No available dates (excluding Saturdays)"
#                         )
#             return [], [], compatible_groups, unscheduled_reasons

#         total_seats = (
#             Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))[
#                 "total"
#             ]
#             or 0
#         )
#         logger.info(f"Total compatible groups to schedule: {len(compatible_groups)}")
#         logger.info(f"Available seats: {total_seats}")

#         enrollments_by_group = prefetch_enrollments(compatible_groups)

#         all_group_ids = set()
#         for group in compatible_groups:
#             for course in group["courses"]:
#                 all_group_ids.update(course["groups"])
#         groups_dict = fetch_course_groups(all_group_ids)

#         exams_created = []
#         unscheduled_groups = []

#         with transaction.atomic():
#             slot_cache = {}

#             for date in dates:
#                 slot_cache[date] = {slot["name"]: slot for slot in slots_by_date[date]}

#             for idx, course_group in enumerate(compatible_groups):
#                 if idx >= len(dates):
#                     unscheduled_groups.extend(compatible_groups[idx:])
#                     for g in compatible_groups[idx:]:
#                         for course in g["courses"]:
#                             for group_id in course["groups"]:
#                                 unscheduled_reasons[group_id] = (
#                                     "No more available dates."
#                                 )
#                     break
#                 slot_usage = {"Morning": 0, "Evening": 0, "Afternoon": 0}
#                 current_date = dates[idx]
#                 weekday = current_date.strftime("%A")
#                 slot_map = slot_cache[current_date]
#                 all_slots = set(slot_map.keys())

#                 group_exams, partially_scheduled, reasons = schedule_group_exams(
#                     idx,
#                     course_group,
#                     current_date,
#                     weekday,
#                     slot_map,
#                     all_slots,
#                     total_seats,
#                     courses_dict,
#                     groups_dict,
#                     enrollments_by_group,
#                     master_timetable,
#                     slot_usage,
#                 )

#                 exams_created.extend(group_exams)

#                 if partially_scheduled or course_group["courses"]:
#                     unscheduled_groups.append(course_group)

#                     for k, v in reasons.items():
#                         if k not in unscheduled_reasons:
#                             unscheduled_reasons[k] = v
#                     logger.info(f"Group {idx + 1} partially scheduled")
#                 else:
#                     logger.info(f"Group {idx + 1} fully scheduled")

#             try:
#                 unaccommodated_students = allocate_shared_rooms(location)
#             except Exception as e:
#                 logger.error(f"Error in room allocation: {e}")
#                 unaccommodated_students = []

#         if exams_created:
#             send_exam_data.delay(
#                 {
#                     "scheduled": len(compatible_groups),
#                     "all_exams": len(compatible_groups),
#                 },
#                 user_id=1,
#                 broadcast=True,
#             )

#         logger.info(
#             f"Scheduling Summary: Created {len(exams_created)} exams, {len(unscheduled_groups)} groups unscheduled."
#         )
#         return (
#             exams_created,
#             unaccommodated_students,
#             unscheduled_groups,
#             unscheduled_reasons,
#         )

#     except Exception as e:
#         logger.error(f"Error generating schedule: {e}")
#         return [], f"Error generating schedule: {e}", [], {}



# def allocate_shared_rooms(location_id):
#     # Get all unassigned student exams with related data
#     student_exams = (
#         StudentExam.objects.filter(room__isnull=True)
#         .select_related("exam", "exam__group__course__semester", "student")
#         .order_by("exam__date", "exam__start_time")
#     )

#     if not student_exams.exists():
#         return []

#     rooms = list(Room.objects.filter(location_id=location_id).order_by("-capacity"))
#     if not rooms:
#         raise Exception("No rooms available for allocation.")

#     # Define time slots
#     SLOTS = [
#         ("Morning", time(8, 0), time(11, 0)),
#         ("Afternoon", time(13, 0), time(16, 0)),
#         ("Evening", time(18, 0), time(20, 0)),
#     ]

#     with transaction.atomic():
#         schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
#         unaccommodated = []

#         # Organize students by date and slot
#         date_slot_students = defaultdict(lambda: defaultdict(list))
#         for se in student_exams:
#             for slot_name, start, end in SLOTS:
#                 if se.exam.slot_name == slot_name:
#                     date_slot_students[se.exam.date][slot_name].append(se)
#                     break

#         # Process each date and slot
#         for date, slots in date_slot_students.items():
#             for slot_name, slot_start, slot_end in SLOTS:
#                 slot_students = slots.get(slot_name, [])
#                 if not slot_students:
#                     continue

#                 # Group by exam
#                 exams = defaultdict(list)
#                 for se in slot_students:
#                     exams[se.exam].append(se)

#                 # Sort exams (largest first for pairing)
#                 sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))

#                 room_index = 0
#                 remaining_students = slot_students.copy()

#                 while remaining_students and room_index < len(rooms):
#                     room = rooms[room_index]
#                     room_index += 1

#                     if room.id in schedule[date][slot_name]:
#                         continue

#                     available = room.capacity
#                     if available <= 0:
#                         continue

#                     # --- Try to find the best pair ---
#                     best_pair = None
#                     max_fill = 0

#                     for i in range(len(sorted_exams)):
#                         exam1, students1 = sorted_exams[i]
#                         if not students1:
#                             continue
#                         for j in range(i + 1, len(sorted_exams)):
#                             exam2, students2 = sorted_exams[j]
#                             if not students2:
#                                 continue

#                             # sem1 = int(exam1.group.course.semester.name.split()[1])
#                             # sem2 = int(exam2.group.course.semester.name.split()[1])
#                             course1 = exam1.group.course.id
#                             course2 = exam2.group.course.id

#                             if course1 != course2:
#                                 # Calculate split sizes (equal proportioning)
#                                 max_each = available // 2
#                                 size1 = min(len(students1), max_each)
#                                 size2 = min(len(students2), max_each)
#                                 total_fill = size1 + size2
#                                 if total_fill > max_fill:
#                                     best_pair = (exam1, exam2, size1, size2)
#                                     max_fill = total_fill

#                     if best_pair:
#                         exam1, exam2, size1, size2 = best_pair
#                         assigned = []

#                         # Assign proportionally
#                         for exam, size in [(exam1, size1), (exam2, size2)]:
#                             exam_students = [
#                                 se for se in remaining_students if se.exam == exam
#                             ][:size]
#                             assigned.extend(exam_students)
#                             for se in exam_students:
#                                 remaining_students.remove(se)
#                                 exams[exam].remove(se)

#                         schedule[date][slot_name][room.id].extend(assigned)

#                     else:
#                         # --- No pair found: assign smallest course alone ---
#                         smallest_exam, students = max(
#                             ((e, s) for e, s in sorted_exams if s),
#                             key=lambda x: len(x[1]),
#                             default=(None, None),
#                         )
#                         if smallest_exam:
#                             to_assign = students[:available]
#                             schedule[date][slot_name][room.id].extend(to_assign)
#                             for se in to_assign:
#                                 remaining_students.remove(se)
#                                 exams[smallest_exam].remove(se)

#                 # Track unassigned students
#                 unaccommodated.extend([se.student for se in remaining_students])

#         # Save all assignments to DB
#         for date, slots in schedule.items():
#             for slot_name, room_assignments in slots.items():
#                 for room_id, student_exams in room_assignments.items():
#                     StudentExam.objects.filter(
#                         id__in=[se.id for se in student_exams]
#                     ).update(room_id=room_id)

#         # Final attempt for leftover students
#         if unaccommodated:
#             remaining_exams = StudentExam.objects.filter(
#                 student__in=unaccommodated, room__isnull=True
#             ).select_related("exam")

#             for se in remaining_exams:
#                 date = se.exam.date
#                 for slot_name, start, end in SLOTS:
#                     if se.exam.start_time == start and se.exam.end_time == end:
#                         for room in rooms:
#                             current = len(schedule[date][slot_name].get(room.id, []))
#                             if current < room.capacity:
#                                 se.room = room
#                                 se.save()
#                                 try:
#                                     unaccommodated.remove(se.student)
#                                 except ValueError:
#                                     pass
#                                 schedule[date][slot_name][room.id].append(se)
#                                 break

#     return unaccommodated




















# Standard Library
from collections import defaultdict, deque
from datetime import datetime, time, timedelta
from itertools import combinations
import heapq
import logging
from pprint import pprint
import random
import copy

# Django
from django.db import transaction
from django.db.models import Count, Sum
from django.utils.timezone import now

# Local Models
from courses.models import Course, CourseGroup
from enrollments.models import Enrollment
from exams.models import Exam, StudentExam
from rooms.models import Room
from schedules.models import MasterTimetable
from django.db.models import Min, Max
from datetime import timedelta, time
from collections import defaultdict
from notifications.tasks import send_exam_data
from collections import defaultdict
from datetime import timedelta
from django.db.models import Min, Max, Prefetch

logger = logging.getLogger(__name__)

SLOTS = [
    ("Morning", time(8, 0), time(11, 0)),
    ("Afternoon", time(13, 0), time(16, 0)),
    ("Evening", time(17, 0), time(20, 0)),
]
FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]
NO_EXAM_DAYS = ["Saturday"]

def get_exam_slots(start_date, end_date, max_slots=None):
    date_slots = []
    current_date = start_date

    while current_date <= end_date:
        weekday = current_date.strftime("%A")
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
                if max_slots and len(date_slots) >= max_slots:
                    break
        current_date += timedelta(days=1)

    return date_slots

def find_compatible_courses_within_group(courses):
    """Keep the same logic but add priority scoring for better scheduling"""
    if not courses:
        return {"compatible_groups": [], "group_conflicts": defaultdict(list)}

    # Get location and total capacity
    location = Course.objects.filter(id=courses[0]).first().department.location.id
    total_seats = (
        Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))[
            "total"
        ]
        or 0
    )
    max_students_per_timeslot = total_seats * 3

    # Get all enrollments and organize data
    course_students = defaultdict(set)
    course_group_details = defaultdict(lambda: defaultdict(list))
    course_group_students = defaultdict(lambda: defaultdict(set))
    course_group_sizes = defaultdict(lambda: defaultdict(int))

    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_students[enrollment.course_id].add(enrollment.student_id)
        course_group_details[enrollment.course_id][enrollment.group_id].append(
            enrollment.student_id
        )
        course_group_students[enrollment.course_id][enrollment.group_id].add(
            enrollment.student_id
        )
        course_group_sizes[enrollment.course_id][enrollment.group_id] += 1

    # Find course conflicts (students taking multiple courses)
    course_conflicts = defaultdict(list)
    for course1, course2 in combinations(course_students.keys(), 2):
        students1 = course_students[course1]
        students2 = course_students[course2]

        if students1 & students2:
            course_conflicts[course1].append(course2)
            course_conflicts[course2].append(course1)

    # First attempt: try to schedule each course with all its groups together
    color_courses = defaultdict(list)
    color_student_counts = defaultdict(int)
    color_course_groups = defaultdict(lambda: defaultdict(list))
    colored = {}

    course_list = sorted(
        course_students.keys(),
        key=lambda x: (-len(course_students[x]), -len(course_conflicts[x])),
    )

    for course in course_list:
        course_student_count = len(course_students[course])
        course_groups = list(course_group_students[course].keys())

        available_colors = []
        for color in range(len(course_students)):
            # Check for conflicts
            is_conflict_free = all(
                colored.get(conflict) != color
                for conflict in course_conflicts[course]
                if conflict in colored
            )

            # Check capacity
            has_capacity = (
                color_student_counts[color] + course_student_count
            ) <= max_students_per_timeslot

            if is_conflict_free and has_capacity:
                available_colors.append(color)

        if available_colors:
            # Place entire course in the best color
            chosen_color = min(available_colors, key=lambda c: color_student_counts[c])
            colored[course] = chosen_color
            color_courses[chosen_color].append(course)
            color_student_counts[chosen_color] += course_student_count

            # Record all groups for this course
            for group_id in course_groups:
                color_course_groups[chosen_color][course].append(group_id)
        else:
            # Course doesn't fit entirely - need to split groups
            sorted_groups = sorted(
                course_groups, key=lambda g: -course_group_sizes[course][g]
            )
            remaining_groups = sorted_groups.copy()

            # Try to place as many groups as possible in adjacent timeslots
            adjacent_colors = set()
            placed_groups = []

            # First pass: try to place groups in existing colors
            for group_id in remaining_groups[:]:
                group_size = course_group_sizes[course][group_id]
                best_color = None
                min_remaining_capacity = float("inf")

                # Find the best color for this group
                for color in range(len(color_student_counts)):
                    if any(
                        colored.get(conflict) == color
                        for conflict in course_conflicts[course]
                        if conflict in colored
                    ):
                        continue

                    remaining_capacity = (
                        max_students_per_timeslot - color_student_counts[color]
                    )
                    if group_size <= remaining_capacity:
                        if (
                            best_color is None
                            or remaining_capacity < min_remaining_capacity
                        ):
                            best_color = color
                            min_remaining_capacity = remaining_capacity

                if best_color is not None:
                    # Place group in best color
                    color_course_groups[best_color][course].append(group_id)
                    color_student_counts[best_color] += group_size
                    placed_groups.append((group_id, best_color))
                    adjacent_colors.add(best_color)
                    remaining_groups.remove(group_id)

            # Second pass: for remaining groups, try to place them adjacent to already placed groups
            for group_id in remaining_groups[:]:
                group_size = course_group_sizes[course][group_id]

                # Try to place near existing groups of the same course
                if adjacent_colors:
                    best_adjacent_color = None
                    min_remaining_capacity = float("inf")

                    for color in adjacent_colors:
                        if any(
                            colored.get(conflict) == color
                            for conflict in course_conflicts[course]
                            if conflict in colored
                        ):
                            continue

                        remaining_capacity = (
                            max_students_per_timeslot - color_student_counts[color]
                        )
                        if group_size <= remaining_capacity:
                            if (
                                best_adjacent_color is None
                                or remaining_capacity < min_remaining_capacity
                            ):
                                best_adjacent_color = color
                                min_remaining_capacity = remaining_capacity

                    if best_adjacent_color is not None:
                        color_course_groups[best_adjacent_color][course].append(
                            group_id
                        )
                        color_student_counts[best_adjacent_color] += group_size
                        placed_groups.append((group_id, best_adjacent_color))
                        remaining_groups.remove(group_id)
                        continue

                # If no adjacent slot available, create new color near existing ones
                if adjacent_colors:
                    # Create new color with minimal distance from existing ones
                    new_color = (
                        max(adjacent_colors) + 1
                        if max(adjacent_colors) + 1 not in adjacent_colors
                        else min(adjacent_colors) - 1
                    )
                    if new_color < 0:
                        new_color = max(adjacent_colors) + 1
                else:
                    # No groups placed yet, create new color
                    new_color = len(color_student_counts)

                # Initialize new color if needed
                if new_color not in color_student_counts:
                    color_student_counts[new_color] = 0

                color_course_groups[new_color][course].append(group_id)
                color_student_counts[new_color] += group_size
                placed_groups.append((group_id, new_color))
                adjacent_colors.add(new_color)
                remaining_groups.remove(group_id)

    # Convert to compatible groups format with priority scoring
    compatible_groups = []
    for color in sorted(color_course_groups.keys()):
        courses_in_slot = []
        total_students = 0
        conflict_count = 0

        for course_id, group_ids in color_course_groups[color].items():
            course_student_count = sum(
                course_group_sizes[course_id][group_id] for group_id in group_ids
            )
            total_students += course_student_count
            conflict_count += len(course_conflicts[course_id])

            courses_in_slot.append(
                {
                    "course_id": course_id,
                    "groups": group_ids,
                    "student_count": course_student_count,
                    "all_groups_scheduled_together": len(group_ids)
                    == len(course_group_students[course_id]),
                    "split_course": len(group_ids)
                    < len(course_group_students[course_id]),
                }
            )

        # Calculate priority score (higher = schedule first)
        priority_score = total_students + conflict_count * 10

        compatible_groups.append(
            {
                "timeslot": color + 1,
                "courses": courses_in_slot,
                "student_count": total_students,
                "within_capacity": total_students <= max_students_per_timeslot,
                "priority_score": priority_score,  # NEW: Add priority for scheduling
                "scheduling_difficulty": conflict_count,  # NEW: Track scheduling difficulty
            }
        )

    # Sort by priority (highest priority first for scheduling)
    compatible_groups.sort(key=lambda x: (-x["priority_score"], -x["student_count"]))

    return compatible_groups, course_conflicts

def create_slot_availability_matrix(slots_by_date, total_seats):
    """Create a matrix tracking availability of each slot"""
    slot_matrix = {}
    
    for date, day_slots in slots_by_date.items():
        if date.strftime("%A") == "Saturday":
            continue
            
        for slot_info in day_slots:
            slot_key = f"{date}_{slot_info['name']}"
            slot_matrix[slot_key] = {
                'date': date,
                'slot_name': slot_info['name'],
                'slot_info': slot_info,
                'used_capacity': 0,
                'max_capacity': total_seats,
                'available_capacity': total_seats
            }
    
    return slot_matrix

def find_best_slot_for_group(group, slot_matrix):
    """Find the best available slot for a group"""
    suitable_slots = []
    
    for slot_key, slot_data in slot_matrix.items():
        if slot_data['available_capacity'] >= group['student_count']:
            # Calculate efficiency score (how well this slot will be utilized)
            utilization_after = (slot_data['used_capacity'] + group['student_count']) / slot_data['max_capacity']
            
            # Prefer slots that will be well-utilized but not completely full
            # This leaves some room for other groups if needed
            efficiency_score = utilization_after if utilization_after <= 0.9 else 0.9 - (utilization_after - 0.9)
            
            suitable_slots.append((slot_key, efficiency_score, slot_data))
    
    if not suitable_slots:
        return None
    
    # Sort by efficiency score (descending)
    suitable_slots.sort(key=lambda x: x[1], reverse=True)
    return suitable_slots[0]  # Return best slot

def get_exam_time_for_group(weekday, available_slots, available_seats=None, slots_usage=None, needed_seats=None):
    """Modified to work with the new slot selection logic"""
    if weekday == "Saturday":
        return None

    # Find a slot that can accommodate the needed seats
    for slot, number in slots_usage.items():
        if number + needed_seats <= available_seats:
            return slot
    return None

def fetch_courses(course_ids):
    if course_ids:
        return {c.id: c for c in Course.objects.filter(id__in=course_ids)}
    # else fetch all courses with enrollments
    courses_qs = Course.objects.annotate(enrollment_count=Count("enrollments")).filter(
        enrollment_count__gt=0
    )
    return {c.id: c for c in courses_qs}

def fetch_course_groups(group_ids):
    return {g.id: g for g in CourseGroup.objects.filter(id__in=group_ids)}

def get_slots_by_date(slots_input):
    slots_by_date = {}
    for date_str, value in slots_input.items():
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slots_by_date[date] = value
    return slots_by_date

def prefetch_enrollments(course_groups):
    course_group_ids = set()
    for group in course_groups:
        for course in group["courses"]:
            course_group_ids.update(course["groups"])
    enrollments_qs = (
        Enrollment.objects.filter(group_id__in=course_group_ids)
        .select_related("student")
        .values("group_id", "student_id")
    )
    enrollments_by_group = defaultdict(list)
    for enrollment in enrollments_qs:
        enrollments_by_group[enrollment["group_id"]].append(enrollment["student_id"])
    return enrollments_by_group

def schedule_group_exams(
    group_idx,
    course_group,
    current_date,
    weekday,
    slot_map,
    all_slots,
    all_available_seats,
    courses_dict,
    groups_dict,
    enrollments_by_group,
    master_timetable,
    slot_seats_usage,
):
    """Keep the same signature but optimize the internal logic"""
    exams_created = []
    unscheduled_reasons = {}
    partially_scheduled = False

    for course_idx, course_dict in enumerate(course_group["courses"]):
        course_id = course_dict["course_id"]
        if course_id not in courses_dict:
            logger.warning(f"Course with id {course_id} not found")
            continue

        course = courses_dict[course_id]
        remaining_groups = []
        for group_id in course_dict["groups"]:
            if group_id not in groups_dict:
                logger.warning(f"Group with id {group_id} not found")
                continue

            group = groups_dict[group_id]
            student_ids = enrollments_by_group.get(group_id, [])

            if not student_ids:
                logger.info(f"No enrollments found for group {group_id}")
                unscheduled_reasons[group_id] = "No enrolled students"
                partially_scheduled = True
                continue
                
            needed_seats = len(student_ids)
            slot_name = get_exam_time_for_group(
                weekday, all_slots, all_available_seats, slot_seats_usage, needed_seats
            )
            
            if slot_name not in slot_map:
                reason = f"No valid time slot for group {group.group_name} on {weekday}"
                logger.info(reason)
                unscheduled_reasons[group_id] = reason
                partially_scheduled = True
                continue

            wanted_slot = slot_map[slot_name]
            start_time = time(*map(int, wanted_slot["start"].split(":")))
            end_time = time(*map(int, wanted_slot["end"].split(":")))

            if slot_seats_usage[slot_name] + needed_seats > all_available_seats:
                reason = (
                    f"Not enough seats for course {course_id}, group {group_id} in {slot_name} slot "
                    f"(Required: {needed_seats}, Available: {all_available_seats - slot_seats_usage[slot_name]})"
                )
                logger.info(reason)
                unscheduled_reasons[group_id] = reason
                partially_scheduled = True
                continue

            try:
                exam = Exam.objects.create(
                    date=current_date,
                    start_time=start_time,
                    end_time=end_time,
                    group=group,
                    slot_name=slot_name,
                )
                master_timetable.exams.add(exam)
                exams_created.append(exam)

                student_exam_objs = [
                    StudentExam(student_id=student_id, exam=exam)
                    for student_id in student_ids
                ]
                StudentExam.objects.bulk_create(student_exam_objs)

                slot_seats_usage[slot_name] += needed_seats
                logger.debug(
                    f"Scheduled course {course_id}, group {group_id} at {start_time}–{end_time}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to create exam for course {course_id}, group {group_id}: {e}"
                )
                unscheduled_reasons[group_id] = str(e)
                partially_scheduled = True
                remaining_groups.append(group_id)

        # Update groups for this course to only those not scheduled
        course_dict["groups"] = remaining_groups

    # Clean courses with no groups left
    course_group["courses"] = [c for c in course_group["courses"] if c["groups"]]

    return exams_created, partially_scheduled, unscheduled_reasons

def generate_exam_schedule(
    slots=None, course_ids=None, master_timetable: MasterTimetable = None, location=None
):
    """Enhanced version that optimizes slot utilization while maintaining the same interface"""
    try:
        courses_dict = fetch_courses(course_ids)
        enrolled_course_ids = list(courses_dict.keys())
        compatible_groups, _ = find_compatible_courses_within_group(enrolled_course_ids)
        
        unscheduled_reasons = {}

        if not compatible_groups:
            logger.info("No compatible course groups found")
            return [], "No compatible course groups found", [], {}

        slots_by_date = get_slots_by_date(slots)
        
        # Create slot availability matrix
        total_seats = (
            Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))[
                "total"
            ]
            or 0
        )
        slot_matrix = create_slot_availability_matrix(slots_by_date, total_seats)

        if not slot_matrix:
            logger.info("No available slots found")
            for group in compatible_groups:
                for course in group["courses"]:
                    for group_id in course["groups"]:
                        unscheduled_reasons[group_id] = "No available slots"
            return [], [], compatible_groups, unscheduled_reasons

        logger.info(f"Total compatible groups to schedule: {len(compatible_groups)}")
        logger.info(f"Available slots: {len(slot_matrix)}")
        logger.info(f"Available seats per slot: {total_seats}")

        # Print utilization planning
        print("\n=== SCHEDULING OPTIMIZATION ===")
        for i, group in enumerate(compatible_groups):
            print(f"Group {i+1}: {group['student_count']} students, "
                  f"Priority: {group.get('priority_score', 0)}, "
                  f"Difficulty: {group.get('scheduling_difficulty', 0)}")

        enrollments_by_group = prefetch_enrollments(compatible_groups)

        all_group_ids = set()
        for group in compatible_groups:
            for course in group["courses"]:
                all_group_ids.update(course["groups"])
        groups_dict = fetch_course_groups(all_group_ids)

        exams_created = []
        unscheduled_groups = []
        scheduled_assignments = []

        with transaction.atomic():
            # NEW: Optimized slot assignment
            for group_idx, course_group in enumerate(compatible_groups):
                # Find best slot for this group
                best_slot_info = find_best_slot_for_group(course_group, slot_matrix)
                
                if not best_slot_info:
                    # No slot can accommodate this group
                    unscheduled_groups.append(course_group)
                    for course in course_group["courses"]:
                        for group_id in course["groups"]:
                            unscheduled_reasons[group_id] = (
                                f"No slot available with {course_group['student_count']} seats capacity"
                            )
                    continue

                slot_key, efficiency_score, slot_data = best_slot_info
                current_date = slot_data['date']
                weekday = current_date.strftime("%A")
                
                # Reserve the capacity in the slot matrix
                slot_matrix[slot_key]['used_capacity'] += course_group['student_count']
                slot_matrix[slot_key]['available_capacity'] -= course_group['student_count']
                
                scheduled_assignments.append((group_idx, current_date, slot_data['slot_name'], efficiency_score))
                
                # Create slot map for this date (maintaining existing interface)
                day_slots = slots_by_date[current_date]
                slot_map = {slot["name"]: slot for slot in day_slots}
                all_slots = set(slot_map.keys())
                
                # Initialize slot usage for this day
                slot_usage = {slot_name: 0 for slot_name in all_slots}
                
                # Add existing usage from slot matrix for this day
                for existing_slot_key, existing_slot_data in slot_matrix.items():
                    if existing_slot_data['date'] == current_date:
                        slot_usage[existing_slot_data['slot_name']] = existing_slot_data['used_capacity']

                group_exams, partially_scheduled, reasons = schedule_group_exams(
                    group_idx,
                    course_group,
                    current_date,
                    weekday,
                    slot_map,
                    all_slots,
                    total_seats,
                    courses_dict,
                    groups_dict,
                    enrollments_by_group,
                    master_timetable,
                    slot_usage,
                )

                exams_created.extend(group_exams)

                if partially_scheduled or course_group["courses"]:
                    unscheduled_groups.append(course_group)
                    for k, v in reasons.items():
                        if k not in unscheduled_reasons:
                            unscheduled_reasons[k] = v
                    logger.info(f"Group {group_idx + 1} partially scheduled")
                else:
                    logger.info(f"Group {group_idx + 1} fully scheduled on {current_date} {slot_data['slot_name']} (efficiency: {efficiency_score:.2f})")

            # Print final utilization report
            print_final_utilization_report(slot_matrix, scheduled_assignments)

            try:
                unaccommodated_students = allocate_shared_rooms(location)
            except Exception as e:
                logger.error(f"Error in room allocation: {e}")
                unaccommodated_students = []

        if exams_created:
            send_exam_data.delay(
                {
                    "scheduled": len([g for g in compatible_groups if g not in unscheduled_groups]),
                    "all_exams": len(compatible_groups),
                },
                user_id=1,
                broadcast=True,
            )

        logger.info(
            f"Optimized Scheduling Summary: Created {len(exams_created)} exams, "
            f"{len(unscheduled_groups)} groups unscheduled."
        )
        return (
            exams_created,
            unaccommodated_students,
            unscheduled_groups,
            unscheduled_reasons,
        )

    except Exception as e:
        logger.error(f"Error generating schedule: {e}")
        return [], f"Error generating schedule: {e}", [], {}

def print_final_utilization_report(slot_matrix, scheduled_assignments):
    """Print how well the scheduling algorithm utilized available slots"""
    print("\n=== FINAL SLOT UTILIZATION REPORT ===")
    
    utilization_by_date = defaultdict(lambda: defaultdict(lambda: {'used': 0, 'total': 0}))
    
    for slot_key, slot_data in slot_matrix.items():
        date = slot_data['date']
        slot_name = slot_data['slot_name']
        utilization_by_date[date][slot_name]['used'] = slot_data['used_capacity']
        utilization_by_date[date][slot_name]['total'] = slot_data['max_capacity']
    
    for date in sorted(utilization_by_date.keys()):
        print(f"\n{date} ({date.strftime('%A')}):")
        day_total_used = 0
        day_total_capacity = 0
        
        for slot_name, data in utilization_by_date[date].items():
            used = data['used']
            total = data['total']
            day_total_used += used
            day_total_capacity += total
            
            utilization_pct = (used / total * 100) if total > 0 else 0
            status = "FULL" if used >= total else "USED" if used > 0 else "EMPTY"
            print(f"  {slot_name}: {used}/{total} ({utilization_pct:.1f}%) - {status}")
        
        day_utilization = (day_total_used / day_total_capacity * 100) if day_total_capacity > 0 else 0
        print(f"  Day Total: {day_total_used}/{day_total_capacity} ({day_utilization:.1f}%)")
    
    # Overall statistics
    total_used = sum(slot_data['used_capacity'] for slot_data in slot_matrix.values())
    total_capacity = sum(slot_data['max_capacity'] for slot_data in slot_matrix.values())
    overall_utilization = (total_used / total_capacity * 100) if total_capacity > 0 else 0
    
    print(f"\n=== OVERALL UTILIZATION ===")
    print(f"Total Capacity Used: {total_used}/{total_capacity} ({overall_utilization:.1f}%)")
    print(f"Scheduled Assignments: {len(scheduled_assignments)}")

def allocate_shared_rooms(location_id):
    """Keep the existing room allocation logic unchanged"""
    # Get all unassigned student exams with related data
    student_exams = (
        StudentExam.objects.filter(room__isnull=True)
        .select_related("exam", "exam__group__course__semester", "student")
        .order_by("exam__date", "exam__start_time")
    )

    if not student_exams.exists():
        return []

    rooms = list(Room.objects.filter(location_id=location_id).order_by("-capacity"))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    # Define time slots
    SLOTS = [
        ("Morning", time(8, 0), time(11, 0)),
        ("Afternoon", time(13, 0), time(16, 0)),
        ("Evening", time(18, 0), time(20, 0)),
    ]

    with transaction.atomic():
        schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        unaccommodated = []

        # Organize students by date and slot
        date_slot_students = defaultdict(lambda: defaultdict(list))
        for se in student_exams:
            for slot_name, start, end in SLOTS:
                if se.exam.slot_name == slot_name:
                    date_slot_students[se.exam.date][slot_name].append(se)
                    break

        # Process each date and slot
        for date, slots in date_slot_students.items():
            for slot_name, slot_start, slot_end in SLOTS:
                slot_students = slots.get(slot_name, [])
                if not slot_students:
                    continue

                # Group by exam
                exams = defaultdict(list)
                for se in slot_students:
                    exams[se.exam].append(se)

                # Sort exams (largest first for pairing)
                sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))

                room_index = 0
                remaining_students = slot_students.copy()

                while remaining_students and room_index < len(rooms):
                    room = rooms[room_index]
                    room_index += 1

                    if room.id in schedule[date][slot_name]:
                        continue

                    available = room.capacity
                    if available <= 0:
                        continue

                    # --- Try to find the best pair ---
                    best_pair = None
                    max_fill = 0

                    for i in range(len(sorted_exams)):
                        exam1, students1 = sorted_exams[i]
                        if not students1:
                            continue
                        for j in range(i + 1, len(sorted_exams)):
                            exam2, students2 = sorted_exams[j]
                            if not students2:
                                continue

                            course1 = exam1.group.course.id
                            course2 = exam2.group.course.id

                            if course1 != course2:
                                # Calculate split sizes (equal proportioning)
                                max_each = available // 2
                                size1 = min(len(students1), max_each)
                                size2 = min(len(students2), max_each)
                                total_fill = size1 + size2
                                if total_fill > max_fill:
                                    best_pair = (exam1, exam2, size1, size2)
                                    max_fill = total_fill

                    if best_pair:
                        exam1, exam2, size1, size2 = best_pair
                        assigned = []

                        # Assign proportionally
                        for exam, size in [(exam1, size1), (exam2, size2)]:
                            exam_students = [
                                se for se in remaining_students if se.exam == exam
                            ][:size]
                            assigned.extend(exam_students)
                            for se in exam_students:
                                remaining_students.remove(se)
                                exams[exam].remove(se)

                        schedule[date][slot_name][room.id].extend(assigned)

                    else:
                        # --- No pair found: assign smallest course alone ---
                        smallest_exam, students = max(
                            ((e, s) for e, s in sorted_exams if s),
                            key=lambda x: len(x[1]),
                            default=(None, None),
                        )
                        if smallest_exam:
                            to_assign = students[:available]
                            schedule[date][slot_name][room.id].extend(to_assign)
                            for se in to_assign:
                                remaining_students.remove(se)
                                exams[smallest_exam].remove(se)

                # Track unassigned students
                unaccommodated.extend([se.student for se in remaining_students])

        # Save all assignments to DB
        for date, slots in schedule.items():
            for slot_name, room_assignments in slots.items():
                for room_id, student_exams in room_assignments.items():
                    StudentExam.objects.filter(
                        id__in=[se.id for se in student_exams]
                    ).update(room_id=room_id)

        # Final attempt for leftover students
        if unaccommodated:
            remaining_exams = StudentExam.objects.filter(
                student__in=unaccommodated, room__isnull=True
            ).select_related("exam")

            for se in remaining_exams:
                date = se.exam.date
                for slot_name, start, end in SLOTS:
                    if se.exam.start_time == start and se.exam.end_time == end:
                        for room in rooms:
                            current = len(schedule[date][slot_name].get(room.id, []))
                            if current < room.capacity:
                                se.room = room
                                se.save()
                                try:
                                    unaccommodated.remove(se.student)
                                except ValueError:
                                    pass
                                schedule[date][slot_name][room.id].append(se)
                                break

    return unaccommodated





def schedule_unscheduled_group(course_id, group_id):
    try:
        # Fetch enrolled student IDs once
        enrolled_students = set(
            Enrollment.objects.filter(
                course_id=course_id, group_id=group_id
            ).values_list("student_id", flat=True)
        )
        if not enrolled_students:
            print(f"No students enrolled in course {course_id}, group {group_id}")
            return False

        # Get exam date range once
        exam_dates = Exam.objects.aggregate(min_date=Min("date"), max_date=Max("date"))
        min_exam_date = exam_dates["min_date"]
        max_exam_date = exam_dates["max_date"]
        if not min_exam_date or not max_exam_date:
            print("No exams found in the system")
            return False

        # Pre-fetch all StudentExam entries for enrolled students grouped by date and slot
        student_exams_qs = StudentExam.objects.filter(student_id__in=enrolled_students)
        # Map: {student_id: {date: set(slot_names)}}
        student_exams_map = defaultdict(lambda: defaultdict(set))
        # Map: {date: {student_id: exam_count}}
        exam_counts_map = defaultdict(lambda: defaultdict(int))

        for se in student_exams_qs.select_related("exam"):
            exam_date = se.exam.date
            student_id = se.student_id
            slot_name = se.exam.slot_name
            student_exams_map[student_id][exam_date].add(slot_name)
            exam_counts_map[exam_date][student_id] += 1

        all_slots = {"Morning", "Afternoon", "Evening"}

        for day_offset in range((max_exam_date - min_exam_date).days + 1):
            current_date = min_exam_date + timedelta(days=day_offset)
            weekday = current_date.strftime("%A")
            if weekday == "Saturday":
                continue
            # Adjust slots for Friday
            day_slots = all_slots.copy()
            if weekday == "Friday":
                day_slots.discard("Evening")

            # Check slot usage per student on this date
            skip_date = False
            for student_id in enrolled_students:
                slots = student_exams_map[student_id].get(current_date, set())
                if len(slots) > 2:
                    skip_date = True
                    break
            if skip_date:
                continue

            # Find common free slots for all students on this date
            common_free_slots = day_slots.copy()
            for student_id in enrolled_students:
                occupied_slots = student_exams_map[student_id].get(current_date, set())
                common_free_slots -= occupied_slots

            if not common_free_slots:
                continue

            # Check exam counts per student for this date
            counts = exam_counts_map[current_date]
            if any(count > 1 for count in counts.values()):
                continue

            # Determine slot name and exam times
            group = CourseGroup.objects.get(id=group_id)
            slot_name = get_exam_time_for_group(group.group_name, weekday, day_slots)
            if slot_name not in common_free_slots:
                # If the group's slot_name is occupied, try other slots
                if common_free_slots:
                    slot_name = next(iter(common_free_slots))
                else:
                    continue

            start_time = time(8, 0) if slot_name == "Morning" else time(13, 0)
            end_time = time(11, 0) if slot_name == "Morning" else time(16, 0)

            location = (
                Enrollment.objects.filter(course_id=course_id, group_id=group_id)
                .first()
                .course.department.location
            )

            # FIXED: Proper room capacity checking without the non-existent function
            rooms = Room.objects.filter(location=location)
            if not rooms:
                print(f"No rooms available at location {location}")
                continue

            # Calculate total room capacity
            total_room_capacity = sum(room.capacity for room in rooms)

            # Calculate students already scheduled in this slot and date
            existing_exams = Exam.objects.filter(date=current_date, slot_name=slot_name)

            # Count unique students already scheduled
            existing_student_ids = set()
            for exam in existing_exams:
                exam_students = Enrollment.objects.filter(
                    course_id=exam.group.course_id, group_id=exam.group_id
                ).values_list("student_id", flat=True)
                existing_student_ids.update(exam_students)

            existing_students_count = len(existing_student_ids)
            new_students_count = len(enrolled_students)

            # Check if total capacity can accommodate all students
            if existing_students_count + new_students_count > total_room_capacity:
                print(
                    f"Not enough room capacity for course {course_id}, group {group_id} on {current_date} in {slot_name} slot"
                )
                continue

            # Create exam and student exams
            exam = Exam.objects.create(
                date=current_date,
                start_time=start_time,
                end_time=end_time,
                group=group,
                slot_name=slot_name,
            )
            student_exams = StudentExam.objects.bulk_create(
                [StudentExam(student_id=sid, exam=exam) for sid in enrolled_students]
            )
            allocate_shared_rooms_updated(student_exams)

            print(f"Scheduled course {course_id}, group {group_id} on {current_date}")
            return True

        # If no suitable date found
        return False

    except Exception as e:
        print(f"Error scheduling course {course_id}, group {group_id}: {e}")
        return False


def allocate_shared_rooms_updated(student_exams):
    """
    Allocate rooms to students for exams, considering room capacities and constraints.
    Attempts to pair exams from different semesters in the same room when possible.
    """
    if not student_exams:
        return []

    # Get location from the first student exam
    location = student_exams[0].exam.group.course.department.location

    # Get all rooms at the location, ordered by capacity (largest first)
    rooms = list(Room.objects.filter(location=location).order_by("-capacity"))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    # Define time slots
    SLOTS = [
        ("Morning", time(8, 0), time(11, 0)),
        ("Afternoon", time(13, 0), time(16, 0)),
        ("Evening", time(18, 0), time(20, 0)),
    ]

    # Check total capacity before proceeding
    total_students = len(student_exams)
    total_capacity = sum(room.capacity for room in rooms)

    if total_students > total_capacity:
        raise Exception(
            f"Not enough room capacity: {total_students} students vs {total_capacity} capacity"
        )

    with transaction.atomic():
        # Data structure: schedule[date][slot_name][room_id] = list of StudentExam objects
        schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        unaccommodated = []

        # Organize students by date and slot
        date_slot_students = defaultdict(lambda: defaultdict(list))
        for se in student_exams:
            exam_date = se.exam.date
            slot_name = se.exam.slot_name

            # Verify the slot exists in our defined slots
            slot_exists = False
            for defined_slot_name, start, end in SLOTS:
                if slot_name == defined_slot_name:
                    slot_exists = True
                    break

            if slot_exists:
                date_slot_students[exam_date][slot_name].append(se)
            else:
                # Handle unknown slot names by adding to unaccommodated
                unaccommodated.append(se.student)
                print(
                    f"Warning: Unknown slot name '{slot_name}' for student {se.student.id}"
                )

        # Process each date and slot
        for date, slots in date_slot_students.items():
            for slot_name, slot_students in slots.items():
                if not slot_students:
                    continue

                # Group students by their exam
                exams = defaultdict(list)
                for se in slot_students:
                    exams[se.exam].append(se)

                # Sort exams by number of students (largest first for better pairing)
                sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))

                # Create a copy of remaining students for this slot
                remaining_students = slot_students.copy()
                room_index = 0

                # Process rooms in order of capacity (largest first)
                while remaining_students and room_index < len(rooms):
                    room = rooms[room_index]
                    room_index += 1

                    # Skip if room is already used in this timeslot (shouldn't happen, but safety check)
                    if room.id in schedule[date][slot_name]:
                        continue

                    available_capacity = room.capacity
                    if available_capacity <= 0:
                        continue

                    # Try to find the best pair of exams for this room
                    best_pair = None
                    max_fill = 0

                    # Look for compatible exam pairs (different semesters, can share room)
                    for i in range(len(sorted_exams)):
                        exam1, students1 = sorted_exams[i]
                        if not students1 or len(students1) > available_capacity:
                            continue

                        # Get semester for exam1
                        try:
                            sem1 = int(exam1.group.course.semester.name.split()[1])
                        except (ValueError, IndexError, AttributeError):
                            # If semester parsing fails, treat as incompatible for pairing
                            continue

                        for j in range(i + 1, len(sorted_exams)):
                            exam2, students2 = sorted_exams[j]
                            if not students2 or len(students2) > available_capacity:
                                continue

                            # Get semester for exam2
                            try:
                                sem2 = int(exam2.group.course.semester.name.split()[1])
                            except (ValueError, IndexError, AttributeError):
                                continue

                            # Check if semesters are compatible (differ by more than 1)
                            if abs(sem1 - sem2) > 1:
                                # Calculate how many students from each exam can fit
                                max_each = available_capacity // 2
                                size1 = min(len(students1), max_each)
                                size2 = min(len(students2), max_each)
                                total_fill = size1 + size2

                                if (
                                    total_fill > max_fill
                                    and total_fill <= available_capacity
                                ):
                                    best_pair = (exam1, exam2, size1, size2)
                                    max_fill = total_fill

                    if best_pair:
                        # Allocate the best pair found
                        exam1, exam2, size1, size2 = best_pair
                        assigned = []

                        # Assign students from first exam
                        exam1_students = [
                            se for se in remaining_students if se.exam == exam1
                        ][:size1]
                        assigned.extend(exam1_students)
                        for se in exam1_students:
                            remaining_students.remove(se)
                            exams[exam1].remove(se)

                        # Assign students from second exam
                        exam2_students = [
                            se for se in remaining_students if se.exam == exam2
                        ][:size2]
                        assigned.extend(exam2_students)
                        for se in exam2_students:
                            remaining_students.remove(se)
                            exams[exam2].remove(se)

                        schedule[date][slot_name][room.id].extend(assigned)

                    else:
                        # No suitable pair found, try to assign a single exam
                        # Find the smallest exam that can fit in the room
                        smallest_exam = None
                        smallest_size = float("inf")

                        for exam, students in sorted_exams:
                            if (
                                students
                                and len(students) <= available_capacity
                                and len(students) < smallest_size
                            ):
                                smallest_exam = exam
                                smallest_size = len(students)

                        if smallest_exam:
                            to_assign = [
                                se
                                for se in remaining_students
                                if se.exam == smallest_exam
                            ][:available_capacity]
                            schedule[date][slot_name][room.id].extend(to_assign)
                            for se in to_assign:
                                remaining_students.remove(se)
                                exams[smallest_exam].remove(se)

                # Add any remaining students to unaccommodated list
                unaccommodated.extend([se.student for se in remaining_students])

        # Save all room assignments to the database
        for date, slots in schedule.items():
            for slot_name, room_assignments in slots.items():
                for room_id, assigned_student_exams in room_assignments.items():
                    student_exam_ids = [se.id for se in assigned_student_exams]
                    StudentExam.objects.filter(id__in=student_exam_ids).update(
                        room_id=room_id
                    )

        # Final attempt to assign any leftover students to any available room space
        if unaccommodated:
            remaining_student_exams = StudentExam.objects.filter(
                student__in=unaccommodated, room__isnull=True
            ).select_related("exam")

            for se in remaining_student_exams:
                date = se.exam.date
                slot_name = se.exam.slot_name

                # Try to find a room with available capacity
                for room in rooms:
                    current_occupancy = len(schedule[date][slot_name].get(room.id, []))
                    if current_occupancy < room.capacity:
                        # Assign to this room
                        se.room = room
                        se.save()

                        # Update our schedule tracking
                        schedule[date][slot_name][room.id].append(se)

                        # Remove from unaccommodated if found
                        try:
                            unaccommodated.remove(se.student)
                        except ValueError:
                            pass
                        break

        return unaccommodated
def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return (
        Room.objects.filter().aggregate(total_capacity=Sum("capacity"))[
            "total_capacity"
        ]
        or 0
    )


 


def check_rooms_availability_for_slots(n_students):
    """
    Check if there are enough rooms available for the given date and time slot
    """
    total_capacity = get_total_room_capacity()

    if total_capacity < n_students:
        return False

    return True


def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
    all_suggestions = []
    all_conflicts = defaultdict(list)
    possible_slots = []

    day_of_week = date.weekday()

    # Early exits for optimization
    if day_of_week == 5:  # Saturday
        all_conflicts["Saturday"].append("No exams can be scheduled on Saturday")
        return new_group, None, all_suggestions, all_conflicts

    if day_of_week == 4 and suggested_slot == "Evening":  # Friday evening
        suggested_slot = "Morning"

    # Get date range once
    date_range = Exam.objects.aggregate(min_date=Min("date"), max_date=Max("date"))
    min_exam_date = date_range["min_date"]
    max_exam_date = date_range["max_date"]

    # Calculate all dates to check upfront
    dates_to_check = []

    # Current date
    dates_to_check.append(date)

    # Past dates (up to min_exam_date)
    current_date = date - timedelta(days=1)
    while current_date >= min_exam_date:
        if current_date.weekday() != 5:  # Skip Saturday
            dates_to_check.append(current_date)
        current_date -= timedelta(days=1)

    # Future dates (up to 14 days or max_exam_date)
    for days_after in range(1, 15):
        future_date = date + timedelta(days=days_after)
        if future_date > max_exam_date or future_date.weekday() == 5:
            continue
        dates_to_check.append(future_date)

    # Bulk fetch all enrolled students for new groups
    enrolled_students_new_group = set(
        Enrollment.objects.filter(group_id__in=new_group).values_list(
            "student_id", flat=True
        )
    )

    # Bulk fetch all exams and related data for the date range
    all_exams = (
        Exam.objects.filter(date__in=dates_to_check)
        .select_related("group", "group__course")
        .prefetch_related(
            Prefetch(
                "studentexam_set",
                queryset=StudentExam.objects.select_related("student"),
            )
        )
    )

    # Pre-process exam data into efficient lookup structures
    exams_by_date_slot = defaultdict(list)
    students_by_date_slot = defaultdict(set)

    for exam in all_exams:
        key = (exam.date, exam.slot_name)
        exams_by_date_slot[key].append(exam)

        # Get all students for this exam
        exam_students = {se.student_id for se in exam.studentexam_set.all()}
        students_by_date_slot[key].update(exam_students)

    def get_available_slots_for_date(check_date):
        """Get available slots for a given date based on day of week"""
        available_slots = ["Morning", "Afternoon", "Evening"]
        if check_date.weekday() == 4:  # Friday
            available_slots.remove("Evening")
        return available_slots

    def check_slot_conflicts_optimized(check_date, slot):
        """Optimized conflict checking using pre-fetched data"""
        key = (check_date, slot)
        slot_students = students_by_date_slot.get(key, set())

        conflicts = []
        conflicting_students = enrolled_students_new_group.intersection(slot_students)

        if conflicting_students:
            # Only get exam details for conflicting students
            slot_exams = exams_by_date_slot.get(key, [])
            for student_id in conflicting_students:
                # Find the exam this student is enrolled in
                for exam in slot_exams:
                    exam_student_ids = {
                        se.student_id for se in exam.studentexam_set.all()
                    }
                    if student_id in exam_student_ids:
                        conflicts.append(
                            {
                                "student": student_id,
                                "group": exam.group.group_name,
                                "course": exam.group.course.title,
                                "date": check_date,
                                "slot": slot,
                            }
                        )
                        break

        return conflicts, len(slot_students)

    def evaluate_slot_optimized(check_date, slot, is_suggested=False):
        """Optimized slot evaluation"""
        conflicts, student_count = check_slot_conflicts_optimized(check_date, slot)
        total_students = len(enrolled_students_new_group) + student_count

        suggestion_type = "Suggested slot" if is_suggested else "Slot"

        if conflicts:
            all_conflicts[check_date].extend(conflicts)
            all_suggestions.append(
                {
                    "suggested": False,
                    "date": check_date,
                    "slot": slot,
                    "reason": f"{suggestion_type} {check_date} {slot} is not available (conflicts)",
                }
            )
            return False

        elif not check_rooms_availability_for_slots(total_students):
            room_msg = f"{check_date} {slot} slot lacks room capacity"
            all_conflicts[check_date].append(room_msg)
            all_suggestions.append(
                {
                    "suggested": False,
                    "date": check_date,
                    "slot": slot,
                    "reason": f"{suggestion_type} {check_date} {slot} is not available (insufficient rooms)",
                }
            )
            return False

        else:
            all_suggestions.append(
                {
                    "suggested": True,
                    "date": check_date,
                    "slot": slot,
                    "reason": f"Slot {check_date} {slot} is available",
                }
            )
            possible_slots.append({"date": check_date, "slot": slot})
            return True

    # Process dates in priority order for early termination
    # Priority: 1) Current date with suggested slot, 2) Current date other slots, 3) Other dates

    # Check suggested slot on current date first
    if evaluate_slot_optimized(date, suggested_slot, is_suggested=True):
        # If suggested slot is available, we can potentially return early
        # depending on requirements
        pass

    # Check other slots on the same day
    available_slots = get_available_slots_for_date(date)
    for slot in available_slots:
        if slot != suggested_slot:
            evaluate_slot_optimized(date, slot)

    # Check other dates only if needed (based on business requirements)
    for check_date in dates_to_check[1:]:  # Skip current date (already checked)
        available_slots = get_available_slots_for_date(check_date)
        for slot in available_slots:
            evaluate_slot_optimized(check_date, slot)

    # Optimized best suggestion finding
    best_suggestion = None
    if possible_slots:
        # Group by date for faster lookup
        slots_by_date = defaultdict(list)
        for slot_info in possible_slots:
            slots_by_date[slot_info["date"]].append(slot_info)

        # Prioritize: same date -> suggested slot -> earliest date
        if date in slots_by_date:
            same_date_slots = slots_by_date[date]
            # Look for suggested slot first
            for slot_info in same_date_slots:
                if slot_info["slot"] == suggested_slot:
                    best_suggestion = slot_info
                    break
            if not best_suggestion:
                best_suggestion = same_date_slots[0]
        else:
            # Find earliest date
            earliest_date = min(slots_by_date.keys())
            best_suggestion = slots_by_date[earliest_date][0]

    return new_group, best_suggestion, all_suggestions, all_conflicts




def verify_groups_compatibility(groups):
    """
    Optimized function to find conflicts between groups based on shared students.
    
    Key optimizations:
    1. Single database query with select_related for better performance
    2. Early termination when processing student conflicts
    3. Set operations for faster intersection checks
    4. Reduced memory allocation with generator expressions
    """
    
    # Single optimized query - fetch all needed data at once
    enrollments = (Enrollment.objects
                  .filter(group_id__in=groups)
                  .select_related('course', 'group')  # Reduce DB hits if needed
                  .values('course_id', 'group_id', 'student_id'))
    
    # Build student sets for each (course, group) combination
    course_group_students = defaultdict(lambda: defaultdict(set))
    student_to_groups = defaultdict(set)  # Track which groups each student is in
    
    for enrollment in enrollments:
        course_id = enrollment['course_id']
        group_id = enrollment['group_id']
        student_id = enrollment['student_id']
        
        course_group_students[course_id][group_id].add(student_id)
        student_to_groups[student_id].add((course_id, group_id))
    
    # Find conflicts by checking students that appear in multiple groups
    group_conflicts = []
    processed_pairs = set()
    
    for student_id, student_groups in student_to_groups.items():
        if len(student_groups) > 1:
            # This student is in multiple groups - check for conflicts
            student_groups_list = list(student_groups)
            
            for i in range(len(student_groups_list)):
                for j in range(i + 1, len(student_groups_list)):
                    course1, group1 = student_groups_list[i]
                    course2, group2 = student_groups_list[j]
                    
                    # Create a consistent pair ordering to avoid duplicates
                    pair = tuple(sorted([(course1, group1), (course2, group2)]))
                    
                    if pair not in processed_pairs:
                        processed_pairs.add(pair)
                        
                        # Get all shared students between these two groups
                        students1 = course_group_students[course1][group1]
                        students2 = course_group_students[course2][group2]
                        shared_students = students1 & students2
                        
                        if shared_students:
                            group_conflicts.append((group1, group2, shared_students))
    
    return group_conflicts