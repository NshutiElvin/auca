# Standard Library
from collections import defaultdict, deque
from datetime import datetime, time, timedelta
from itertools import combinations
import heapq
import logging
from pprint import pprint
import random
import copy  # Added explicitly (missing in original)

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

logger = logging.getLogger(__name__)
GROUP_PREFERENCES = {
    "A": "mostly morning",
    "B": "mostly morning",
    "C": "mixed",
    "D": "mixed",
    "E": "evening",
    "F": "evening",
}

SLOTS = [
    ("Morning", time(8, 0), time(11, 0)),
    ("Afternoon", time(13, 0), time(16, 0)),
    ("Evening", time(17, 0), time(20, 0)),
]
FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]
NO_EXAM_DAYS = ["Saturday"]


def get_preferred_slots_for_group(group_name):
    """
    Get preferred slots for a course group based on GROUP_PREFERENCES
    """
    preference = GROUP_PREFERENCES.get(group_name, "mixed")

    if preference == "mostly morning":
        return [SLOTS[0], SLOTS[1], SLOTS[2]]
    elif preference == "evening":
        return [SLOTS[2], SLOTS[1], SLOTS[0]]
    else:
        return [SLOTS[0], SLOTS[1], SLOTS[2]]


def analyze_student_course_conflicts():
    """
    Analyze which courses have students in common to help with scheduling
    Returns a dictionary where keys are course pairs and values are the count of students enrolled in both
    """
    conflict_matrix = defaultdict(int)

    # Get all enrollments grouped by student
    student_courses = defaultdict(list)
    for enrollment in Enrollment.objects.all():
        student_courses[enrollment.student_id].append(enrollment.course_id)

    # Build conflict matrix
    for student_id, courses in student_courses.items():
        for i, course1 in enumerate(courses):
            for course2 in courses[i + 1 :]:
                course_pair = tuple(sorted([course1, course2]))
                conflict_matrix[course_pair] += 1

    return conflict_matrix


def find_compatible_courses(course_conflict_matrix):

    all_courses = set()
    for course1, course2 in course_conflict_matrix.keys():
        all_courses.add(course1)
        all_courses.add(course2)
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count("enrollments")
    ).filter(enrollment_count__gt=0)

    for course in enrolled_courses.values_list("id", flat=True):
        all_courses.add(course)

    compatibility_graph = {course: set() for course in all_courses}
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if (
                    pair not in course_conflict_matrix
                    or course_conflict_matrix[pair] == 0
                ):
                    compatibility_graph[course1].add(course2)

    remaining_courses = set(all_courses)
    course_groups = []

    while remaining_courses:
        course_group = []

        if remaining_courses:
            course1 = min(
                [c for c in remaining_courses],
                key=lambda c: (
                    len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    )
                    if len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    )
                    > 0
                    else float("inf")
                ),
            )

            course_group.append(course1)
            remaining_courses.remove(course1)

            compatible_with_group = (
                set(compatibility_graph[course1]) & remaining_courses
            )

            while compatible_with_group:
                # Select the course with fewest remaining compatible options (to save harder-to-place courses for later)
                next_course = min(
                    compatible_with_group,
                    key=lambda c: len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    ),
                )

                course_group.append(next_course)
                remaining_courses.remove(next_course)

                # Update the set of courses compatible with the entire group
                compatible_with_group &= set(compatibility_graph[next_course])
                compatible_with_group &= remaining_courses

        if course_group:
            course_groups.append(course_group)

    return course_groups


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


def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return Room.objects.aggregate(total_capacity=Sum("capacity"))["total_capacity"] or 0


def get_course_group(course):
    """
    Extract the group from course name (assuming format like "Course A", "Course B", etc.)
    You may need to modify this based on your actual course naming convention
    """
    # This is a placeholder - adjust based on your actual course model structure
    # Option 1: If course has a group field
    if hasattr(course, "group"):
        return course.group

    # Option 2: If group is in course name
    course_name = course.name or course.title
    if course_name:
        # Extract last character as group (adjust as needed)
        group_char = course_name.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char

    # Option 3: If course code contains group info
    if hasattr(course, "code") and course.code:
        group_char = course.code.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char

    # Default to mixed if no group found
    return "C"


def group_courses_by_preference():
    """
    Group courses by their preference categories and find compatible courses within each group
    """
    # Get all courses with enrollments
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count("enrollments")
    ).filter(enrollment_count__gt=0)

    # Group courses by their preference
    courses_by_preference = defaultdict(list)
    for course in enrolled_courses:
        group = get_course_group(course)
        preference = GROUP_PREFERENCES.get(group, "mixed")
        courses_by_preference[preference].append(course)

    return courses_by_preference


def get_student_exam(student_id, date, start_time):

    return StudentExam.objects.filter(
        student_id=student_id,
        exam__date=date,
        exam__start_time=start_time,
    ).first()


def check_rooms_availability_for_slots(n_students):
    """
    Check if there are enough rooms available for the given date and time slot
    """
    total_capacity = get_total_room_capacity()

    if total_capacity < n_students:
        return False

    return True


def get_occupied_seats_by_time_slot(date, start_time):

    occupied_count = StudentExam.objects.filter(
        exam__date=date,
        exam__start_time=start_time,
    ).count()

    return occupied_count
def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
    """
    Determine which slot is good for students, so that they can't do more than 2 exam in same slot
    Restrictions: No exams on Saturday, No evening exams on Friday
    Returns: tuple of (new_group, best_slot_suggestion, all_suggestions, all_conflicts)
    """
    from django.db.models import Q
    
    # Initialize data structures
    all_suggestions = []
    all_conflicts = defaultdict(list)
    possible_slots = []
    checked_slots = set()  # To avoid duplicates

    # Check if the requested date is valid for scheduling
    day_of_week = date.weekday()  # Monday=0, Sunday=6

    # Saturday restriction
    if day_of_week == 5:  # Saturday
        all_conflicts["Saturday"].append("No exams can be scheduled on Saturday")
        return new_group, None, all_suggestions, all_conflicts

    # Friday evening restriction - adjust suggested slot if needed
    if day_of_week == 4 and suggested_slot == "Evening": 
        suggested_slot = "Morning"  # Change to a valid slot for Friday

    # Get all students enrolled in the new group (assuming new_group is a list of group IDs)
    try:
        enrolled_students_new_group = set(
            Enrollment.objects.filter(
                group_id__in=new_group
            ).values_list("student_id", flat=True)
        )
    except Exception as e:
        all_conflicts["enrollment_error"].append(f"Error getting enrollments: {str(e)}")
        return new_group, None, all_suggestions, all_conflicts

    def has_student_conflicts(check_date, slot_name, students_to_check):
        """Check if any students have conflicts in the given slot"""
        try:
            # Get all exams in this specific slot
            conflicting_exams = Exam.objects.filter(
                date=check_date,
                slot_name=slot_name
            )
            
            if not conflicting_exams.exists():
                return False, []  # No exams = no conflicts
            
            # Get all students who already have exams in this slot
            existing_students = set()
            conflict_details = []
            
            for exam in conflicting_exams:
                exam_students = set(
                    Enrollment.objects.filter(
                        group=exam.group
                    ).values_list("student_id", flat=True)
                )
                
                # Check for overlap with our new group students
                overlapping_students = students_to_check.intersection(exam_students)
                
                if overlapping_students:
                    for student in overlapping_students:
                        conflict_details.append({
                            "student": student,
                            "conflicting_group": exam.group.group_name if exam.group else "Unknown",
                            "conflicting_course": exam.group.course.title if exam.group and exam.group.course else "Unknown",
                            "date": check_date,
                            "slot": slot_name
                        })
                
                existing_students.update(exam_students)
            
            has_conflicts = len(conflict_details) > 0
            return has_conflicts, conflict_details
            
        except Exception as e:
            return True, [{"error": f"Error checking conflicts: {str(e)}"}]

    def check_room_capacity(check_date, slot_name, additional_students_count):
        """Check if there's enough room capacity for additional students"""
        try:
            # Get existing students in this slot
            existing_exams = Exam.objects.filter(
                date=check_date,
                slot_name=slot_name
            )
            
            current_students = 0
            for exam in existing_exams:
                current_students += Enrollment.objects.filter(group=exam.group).count()
            
            total_needed = current_students + additional_students_count
            return check_rooms_availability_for_slots(total_needed)
            
        except Exception as e:
            return False

    def evaluate_slot(check_date, slot_name):
        """Evaluate a specific date/slot combination"""
        slot_key = (check_date, slot_name)
        
        # Skip if already checked
        if slot_key in checked_slots:
            return
        checked_slots.add(slot_key)
        
        # Check day validity
        check_day_of_week = check_date.weekday()
        if check_day_of_week == 5:  # Saturday
            return
        
        # Check slot validity for Friday
        if check_day_of_week == 4 and slot_name == "Evening":  # Friday evening
            return
        
        # Check for student conflicts
        has_conflicts, conflict_details = has_student_conflicts(
            check_date, slot_name, enrolled_students_new_group
        )
        
        if has_conflicts:
            # Add to conflicts
            all_conflicts[str(check_date)].extend(conflict_details)
            all_suggestions.append({
                "suggested": False,
                "date": check_date,
                "slot": slot_name,
                "reason": f"Student conflicts found in {slot_name} slot on {check_date}",
                "conflict_count": len(conflict_details)
            })
        else:
            # No student conflicts, check room capacity
            if check_room_capacity(check_date, slot_name, len(enrolled_students_new_group)):
                # This slot is available!
                all_suggestions.append({
                    "suggested": True,
                    "date": check_date,
                    "slot": slot_name,
                    "reason": f"Slot {slot_name} on {check_date} is available"
                })
                possible_slots.append({"date": check_date, "slot": slot_name})
            else:
                all_suggestions.append({
                    "suggested": False,
                    "date": check_date,
                    "slot": slot_name,
                    "reason": f"Insufficient room capacity for {slot_name} on {check_date}"
                })

    # 1. Check the suggested slot on the requested date first
    evaluate_slot(date, suggested_slot)

    # 2. Check other slots on the same day
    available_slots = ["Morning", "Afternoon", "Evening"]
    if day_of_week == 4:  # Friday
        available_slots = ["Morning", "Afternoon"]  # No evening on Friday
    
    for slot in available_slots:
        if slot != suggested_slot:  # Skip suggested slot (already checked)
            evaluate_slot(date, slot)

    # 3. Check past and future dates only if no slots found on requested date
    if not possible_slots:
        try:
            min_exam_date = Exam.objects.aggregate(Min("date"))["date__min"]
            max_exam_date = Exam.objects.aggregate(Max("date"))["date__max"]
            
            if min_exam_date and max_exam_date:
                # Check past dates (up to 7 days before)
                for days_before in range(1, 8):
                    past_date = date - timedelta(days=days_before)
                    if past_date < min_exam_date:
                        continue
                    
                    past_day = past_date.weekday()
                    if past_day == 5:  # Skip Saturday
                        continue
                    
                    past_slots = ["Morning", "Afternoon", "Evening"]
                    if past_day == 4:  # Friday
                        past_slots = ["Morning", "Afternoon"]
                    
                    for slot in past_slots:
                        evaluate_slot(past_date, slot)
                        # Stop if we found some options
                        if len(possible_slots) >= 3:
                            break
                    
                    if len(possible_slots) >= 3:
                        break

                # Check future dates (up to 14 days after) if still no options
                if not possible_slots:
                    for days_after in range(1, 15):
                        future_date = date + timedelta(days=days_after)
                        if future_date > max_exam_date:
                            continue
                        
                        future_day = future_date.weekday()
                        if future_day == 5:  # Skip Saturday
                            continue
                        
                        future_slots = ["Morning", "Afternoon", "Evening"]
                        if future_day == 4:  # Friday
                            future_slots = ["Morning", "Afternoon"]
                        
                        for slot in future_slots:
                            evaluate_slot(future_date, slot)
                            # Stop if we found some options
                            if len(possible_slots) >= 3:
                                break
                        
                        if len(possible_slots) >= 3:
                            break

        except Exception as e:
            all_conflicts["date_range_error"].append(f"Error checking alternative dates: {str(e)}")

    # 4. Determine the best suggestion
    best_suggestion = None
    if possible_slots:
        # Priority: 1) Same date + suggested slot, 2) Same date + any slot, 3) Earliest date
        
        # Try to find same date with suggested slot
        same_date_suggested = [
            s for s in possible_slots 
            if s["date"] == date and s["slot"] == suggested_slot
        ]
        
        if same_date_suggested:
            best_suggestion = same_date_suggested[0]
        else:
            # Try to find same date with any slot
            same_date_any = [s for s in possible_slots if s["date"] == date]
            if same_date_any:
                best_suggestion = same_date_any[0]
            else:
                # Use earliest available date
                possible_slots.sort(key=lambda x: (x["date"], x["slot"]))
                best_suggestion = possible_slots[0]

    # 5. Remove duplicate suggestions (keep only unique date/slot combinations)
    unique_suggestions = []
    seen_combinations = set()
    
    for suggestion in all_suggestions:
        combo_key = (suggestion["date"], suggestion["slot"])
        if combo_key not in seen_combinations:
            seen_combinations.add(combo_key)
            unique_suggestions.append(suggestion)
    
    # Sort suggestions: available ones first, then by date
    unique_suggestions.sort(key=lambda x: (not x["suggested"], x["date"], x["slot"]))

    return new_group, best_suggestion, unique_suggestions, all_conflicts

# def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
#     """Determine which slot is good for students, so that they can't do more than 2 exam in same slot. even if it is exception
#     Restrictions: No exams on Saturday, No evening exams on Friday
#     Returns: tuple of (new_group, best_slot_suggestion, all_suggestions, all_conflicts)
#     """


#     # Initialize data structures
#     all_suggestions = []
#     all_conflicts = defaultdict(list)
#     possible_slots = []

#     # Check if the requested date is valid for scheduling
#     day_of_week = date.weekday()  # Monday=0, Sunday=6

#     # Saturday restriction
#     if day_of_week == 5:  # Saturday
#         all_conflicts["Saturday"].append("No exams can be scheduled on Saturday")
#         return new_group, None, all_suggestions, all_conflicts

#     # Friday evening restriction
#     if day_of_week == 4 and suggested_slot == "Evening": 
#         suggested_slot = (
#             "Morning"   
#         )

#     enrolled_students_new_group = Enrollment.objects.filter(
#         group_id__in=new_group
#     ).values_list("student_id", flat=True)

#     # Function to check conflicts for a given date and slot
#     def check_slot_conflicts(check_date, slot):
       
       
     
#         conflicts = []
        
#         my_slots=["Morning", "Afternoon", "Evening"]
      
        
#         slots_conflicts={"Morning":{"students":0, "conflicts":0}, "Afternoon":{"students":0, "conflicts":0}, "Evening":{"students":0, "conflicts":0}}
#         best_slots_to_use=[]
#         if check_date.weekday() == 4:  # Friday
#             del slots_conflicts["Evening"]
        
#         for myslot in slots_conflicts.keys():
#             slot_exams = Exam.objects.filter(
#             date=check_date,
#            slot_name=myslot
#         )
#             slot_groups = [exam.group.id for exam in slot_exams]
#             slot_students = Enrollment.objects.filter(group_id__in=slot_groups).values_list(
#                 "student_id", flat=True
#             )
#             intersection= enrolled_students_new_group.intersection(slot_students)
        
#             for student in intersection:
#                 slots_conflicts[myslot]["conflicts"]+=1
#                 slots_conflicts[myslot]["students"]=len(slot_students)
                 
#                 exam = slot_exams.filter(group__enrollment__student_id=student).first()
#                 conflicts.append(
#                     {"student": student,  "group":exam.group.group_name, "course": exam.group.course.title, "date":check_date, "slot":myslot}
#                 )
#         for k,v in slots_conflicts.items():
#             if v["conflicts"]==0:
#                 best_slots_to_use.append({k:v})

#         return conflicts, len(slot_students), best_slots_to_use

#     # Function to evaluate a date and slot combination
#     def evaluate_slot(check_date, slot, is_suggested=False):
#         conflicts, student_count, best_slots_to_use = check_slot_conflicts(check_date, slot)
#         print(best_slots_to_use)
#         total_students = len(enrolled_students_new_group) + student_count

     
      
#         if conflicts:
#             all_conflicts[check_date].extend(conflicts)
          
#             all_suggestions.append(
#                 {
#                     "suggested": False,
#                     "date": check_date,
#                     "slot": slot,
#                     "reason": f"Suggested slot {check_date} {slot} is not available (conflicts)",
#                 }
#             )
          
          
        
            
       
        
#         if best_slots_to_use :
         
#             for myslot in best_slots_to_use:
                
#                 slot, v=list( myslot.items())[0]
#                 if check_rooms_availability_for_slots( v["students"]):
#                     msg = {
#                     "suggested": True,
#                     "date": check_date,
#                     "slot": slot,
#                     "reason": f" None Slot {check_date} {slot} is available",
#                 }
#                     all_suggestions.append(msg)
#                     possible_slots.append({"date": check_date, "slot": slot})
#                 else:
#                     msg = {
#                     "suggested": False,
#                     "date": check_date,
#                     "slot": slot,
#                     "reason": f"No seats {check_date} {slot} are available",
#                 }
#                     all_suggestions.append(msg)


#     # Check suggested slot first
#     evaluate_slot(date, suggested_slot, is_suggested=True)

#     # Check other slots on the same day
#     available_slots = ["Morning", "Afternoon", "Evening"]
#     if day_of_week == 4:  # Friday
#         available_slots.remove("Evening")

#     for slot in available_slots:
#         if slot != suggested_slot:
#             evaluate_slot(date, slot)

#     # Check past dates (up to 7 days before)
#     min_exam_date = Exam.objects.aggregate(Min("date"))["date__min"]
#     max_exam_date = Exam.objects.aggregate(Max("date"))["date__max"]
#     for days_before in range(1, 8):
#         past_date = date - timedelta(days=days_before)
#         if past_date < min_exam_date:  # Don't check before the earliest exam date
#             continue
#         if past_date.weekday() == 5:  # Skip Saturday
#             continue

#         past_available_slots = ["Morning", "Afternoon", "Evening"]
#         if past_date.weekday() == 4:  # Friday
#             past_available_slots.remove("Evening")

#         for slot in past_available_slots:
#             evaluate_slot(past_date, slot)

#     # Check future dates (up to 14 days after)
#     for days_after in range(1, 15):
#         future_date = date + timedelta(days=days_after)
#         if future_date > max_exam_date:  # Don't check beyond the latest exam date
#             continue
#         if future_date.weekday() == 5:  # Skip Saturday
#             continue

#         future_available_slots = ["Morning", "Afternoon", "Evening"]
#         if future_date.weekday() == 4:  # Friday
#             future_available_slots.remove("Evening")

#         for slot in future_available_slots:
#             evaluate_slot(future_date, slot)

#     # Determine best suggestion (prioritizing suggested date, then suggested slot, then earliest date)
#     best_suggestion = None
#     if possible_slots:
#         # Try to find on the same date first
#         same_date_slots = [s for s in possible_slots if s["date"] == date]
#         if same_date_slots:
#             # Try to find the suggested slot first
#             suggested_slot_match = [
#                 s for s in same_date_slots if s["slot"] == suggested_slot
#             ]
#             if suggested_slot_match:
#                 best_suggestion = suggested_slot_match[0]
#             else:
#                 best_suggestion = same_date_slots[0]
#         else:
#             # Find the earliest possible date
#             possible_slots.sort(key=lambda x: x["date"])
#             best_suggestion = possible_slots[0]

#     return new_group, best_suggestion, all_suggestions, all_conflicts


def get_slot_name(start_time, end_time):
    """
    Get the slot name based on start and end times
    """
    if start_time == time(8, 0) and end_time == time(11, 0):
        return "Morning"
    elif start_time == time(13, 0) and end_time == time(16, 0):
        return "Afternoon"
    elif start_time == time(18, 0) and end_time == time(20, 0):
        return "Evening"
    else:
        return None


def verify_groups_compatiblity(groups):

    course_group_students = defaultdict(lambda: defaultdict(list))
    for enrollment in Enrollment.objects.filter(group_id__in=groups).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].append(
            enrollment.student_id
        )
    all_groups = [
        (course_id, group_id)
        for course_id in course_group_students
        for group_id in course_group_students[course_id]
    ]
    group_conflicts = []
    for (course1, group1), (course2, group2) in combinations(all_groups, 2):
        students1 = set(course_group_students[course1][group1])
        students2 = set(course_group_students[course2][group2])

        shared_students = students1 & students2
        if shared_students:   
            group_conflicts.append(
                (group1, group2, shared_students)
            )   
    return group_conflicts


def find_compatible_courses_within_group(courses):
    if not courses:
        return {"compatible_groups": [], "group_conflicts": defaultdict(list)}

    # Data structure: {course_id: {group_id: [student_ids]}}
    course_group_students = defaultdict(lambda: defaultdict(list))

    # Populate enrollment data
    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].append(
            enrollment.student_id
        )

    # Generate all group pairs across courses
    all_groups = [
        (course_id, group_id)
        for course_id in course_group_students
        for group_id in course_group_students[course_id]
    ]

    # Build group-level conflict graph
    group_conflicts = defaultdict(list)
    for (course1, group1), (course2, group2) in combinations(all_groups, 2):
        students1 = set(course_group_students[course1][group1])
        students2 = set(course_group_students[course2][group2])

        if students1 & students2:  # Shared students exist
            group_conflicts[(course1, group1)].append((course2, group2))
            group_conflicts[(course2, group2)].append((course1, group1))

    # Greedy graph coloring for groups
    color_groups = defaultdict(list)
    colored = {}
    group_list = sorted(all_groups, key=lambda x: -len(group_conflicts[x]))

    for group in group_list:
        # Find used colors in conflicting groups
        used_colors = {
            colored[conflict]
            for conflict in group_conflicts[group]
            if conflict in colored
        }

        # Assign first available color
        for color in range(len(all_groups)):
            if color not in used_colors:
                colored[group] = color
                color_groups[color].append(group)
                break

    # Convert to compatible groups format
    compatible_groups = []
    for color, groups in color_groups.items():
        # Group by course to maintain structure
        course_map = defaultdict(list)
        for course_id, group_id in groups:
            course_map[course_id].append(group_id)

        compatible_groups.append(
            {
                "timeslot": color + 1,
                "courses": [
                    {"course_id": course_id, "groups": group_ids}
                    for course_id, group_ids in course_map.items()
                ],
                "student_count": sum(
                    len(course_group_students[course_id][group_id])
                    for course_id, group_id in groups
                ),
            }
        )

    compatible_groups.sort(key=lambda x: -x["student_count"])
    return compatible_groups, group_conflicts


def has_sufficient_gap(student_exam_dates, proposed_date, min_gap_days=2):
    """
    Check if scheduling an exam on proposed_date would maintain minimum gap
    """
    if not student_exam_dates:
        return True

    all_dates = student_exam_dates + [proposed_date]
    all_dates.sort()

    for i in range(len(all_dates) - 1):
        gap = (all_dates[i + 1] - all_dates[i]).days
        if gap < min_gap_days:
            return False

    return True


def can_schedule_course_group_on_slot(group, course, proposed_date, student_exam_dates):

    conflicts = []
    # slot_label, start_time, end_time = slot_info

    student_ids = Enrollment.objects.filter(course=course, group=group).values_list(
        "student_id", flat=True
    )

    for student_id in student_ids:
        current_exam_dates = student_exam_dates.get(student_id, [])

        # Check for same-day conflict
        if proposed_date in current_exam_dates:
            conflicts.append(
                f"Student {student_id} already has exam on {proposed_date}"
            )
            continue

        # Check for day-off constraint
        if not has_sufficient_gap(current_exam_dates, proposed_date):
            conflicts.append(f"Student {student_id} would not have sufficient gap")

    return len(conflicts) == 0, conflicts


def remove_scheduled_group(scheduled_groups, course_id, group_id):
    """Remove a specific group from scheduled groups"""
    for course_group in scheduled_groups:
        for course_dict in course_group["courses"]:
            if (
                course_dict["course_id"] == course_id
                and group_id in course_dict["groups"]
            ):
                course_dict["groups"].remove(group_id)
                return True
    return False


def clean_empty_courses_from_group(course_group):
    """Remove courses with no groups from a course_group"""
    course_group["courses"] = [
        course for course in course_group["courses"] if course["groups"]
    ]
    return len(course_group["courses"]) > 0

 

def get_exam_time_for_group(group_name, weekday, available_slots):
    # Step 1: Determine the group's preferred time slot
    preferred_time = determine_preferred_time(group_name, weekday)
    
    # Step 2: If preferred time is available, return it
    if preferred_time in available_slots:
        return preferred_time
    
    # Step 3: Group-specific fallback priorities
    fallback_priority = get_fallback_priority(group_name, weekday)
    
    # Step 4: Return the highest priority available fallback
    for time_slot in fallback_priority:
        if time_slot in available_slots:
            return time_slot
    
    # Step 5: No slots available (edge case)
    return None

def determine_preferred_time(group_name, weekday):
    """Determine the group's preferred time based on business rules"""
    extra=["G", "H","I","J","K","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z"]
    if group_name in ["A", "B"]:
        return "Morning" if random.randint(1, 2) == 1 else "Afternoon"
    elif group_name in ["C", "D"]:
        if weekday == "Friday":
            return "Afternoon"
        return random.choice(["Morning", "Afternoon", "Evening"])
    elif group_name in ["E", "F"]:
        return "Evening" if weekday != "Friday" else "Afternoon"
    elif group_name in extra:
         if random.randint(1, len(extra)-1) %2==0:
             return random.choice(["Morning","Afternoon"])
         else:
             if weekday != "Friday":
                 
                return random.choice(["Evening","Afternoon"])
             else:
                 return "Afternoon"
    else:
        return "Afternoon"

def get_fallback_priority(group_name, weekday):
    """Group-specific fallback priorities when preferred time isn't available"""
    if group_name in ["A", "B"]:
        return ["Afternoon", "Morning", "Evening"]  # Prefer Afternoon over Morning if possible
    elif group_name in ["C", "D"]:
        if weekday == "Friday":
            return ["Morning", "Evening"]  # Afternoon was preferred but unavailable
        return ["Afternoon", "Evening", "Morning"]  # Original preference order
    elif group_name in ["E", "F"]:
        return ["Afternoon", "Morning"]  # Evening was preferred but unavailable
    else:
        return ["Morning", "Evening"]  # Default fallback 

 

def generate_exam_schedule(
    slots=None, course_ids=None, master_timetable: MasterTimetable = None
):
    

    try:
       
        if course_ids:
            enrolled_courses = course_ids
        else:
            enrolled_courses = Course.objects.annotate(
                enrollment_count=Count("enrollments")
            ).filter(enrollment_count__gt=0)

        # Find compatible groups
        compatible_groups, _ = find_compatible_courses_within_group(enrolled_courses)
        unscheduled_reasons={}
        if not compatible_groups:
            print("No compatible course groups found")
            return [], "No compatible course groups found", []

        slots_by_date = {
            datetime.strptime(date_str, "%Y-%m-%d").date(): value
            for date_str, value in slots.items()
        }

        # Initialize tracking variables
        remaining_groups = copy.deepcopy(compatible_groups)
        unscheduled_groups = []
        exams_created = []
        student_exam_dates = defaultdict(list)
        scheduled_exams_per_date = defaultdict(list)

        # Get total available seats
        all_available_seats = (
            Room.objects.order_by("-capacity").aggregate(total=Sum("capacity"))["total"]
            or 0
        )

        print(f"Total compatible groups to schedule: {len(compatible_groups)}")
        print(f"Available seats: {all_available_seats}")

        with transaction.atomic():
            dates = sorted(slots_by_date.keys())
            date_index = 0

            # Process each compatible group on its own day
            for group_idx, course_group in enumerate(compatible_groups):
                # Find next available date (skip Saturdays)
                while date_index < len(dates):
                    current_date = dates[date_index]
                    weekday = current_date.strftime("%A")

                    if weekday != "Saturday":
                        break
                    date_index += 1

                # Check if we have available dates
                if date_index >= len(dates):
                    print(
                        f"No more available dates. Remaining groups will be unscheduled."
                    )
                    unscheduled_groups.extend(remaining_groups[group_idx:])
                    for g in remaining_groups[group_idx:]:
                        for course in g["courses"]:
                            for group in course["groups"]:
                                 unscheduled_reasons[group]=f"No more available dates."

                    break

                current_date = dates[date_index]
                weekday = current_date.strftime("%A")

                print(f"Scheduling group {group_idx + 1} on {current_date} ({weekday})")

                # Track slot usage for this date
                slot_seats_usage = {"Morning": 0, "Evening": 0, "Afternoon": 0}
                group_fully_scheduled = True
                current_group = remaining_groups[group_idx]

                # Process all courses in this compatible group
                for course_dict in current_group["courses"][
                    :
                ]:  # Create copy to iterate
                    course_id = course_dict["course_id"]
                    course_groups = course_dict["groups"][:]  

                    try:
                        course = Course.objects.get(id=course_id)
                    except Course.DoesNotExist:
                        print(f"Course with id {course_id} not found")
                        continue

                    # Process all groups for this course
                    for group_id in course_groups:
                        try:
                            group = CourseGroup.objects.get(id=group_id)
                        except CourseGroup.DoesNotExist:
                            print(f"Group with id {group_id} not found")
                            continue

                        # Get students for this group
                        student_ids = list(
                            Enrollment.objects.filter(
                                course=course, group=group
                            ).values_list("student_id", flat=True)
                        )

                        if not student_ids:
                            # Remove empty groups
                            remove_scheduled_group(
                                remaining_groups, course_id, group_id
                            )
                            continue
                        all_slots = set()
                        for slot in slots_by_date[current_date]:
                            all_slots.add(slot["name"])
                        # Determine exam time based on group and day
                        slot_name = get_exam_time_for_group(
                            group.group_name, weekday, all_slots
                        )
                        wanted_slot= list(filter(lambda x: x["name"]==slot_name, slots_by_date[current_date]))[0]
                        start_time = time( *map(int, wanted_slot["start"].split(":")))
                        end_time = time( *map(int, wanted_slot["end"].split(":")))

                        if not start_time or not end_time:
                            print(
                                f"No valid time slot for group {group.group_name} on {weekday}"
                            )
                            group_fully_scheduled = False
                            continue

                        # slot_name = get_slot_name(start_time, end_time)

                        # Check if we have enough seats for this slot
                        if (
                            slot_seats_usage[slot_name] + len(student_ids)
                            <= all_available_seats
                        ):
                            try:
                                # Create the exam
                                exam = Exam.objects.create(
                                    date=current_date,
                                    start_time=start_time,
                                    end_time=end_time,
                                    group=group,
                                    slot_name=slot_name
                                )
                                master_timetable.exams.add(exam)
                                exams_created.append(exam)

                                # Create student exams
                                for student_id in student_ids:
                                    student_exam = StudentExam.objects.create(
                                        student_id=student_id, exam=exam
                                    )
                                    scheduled_exams_per_date[current_date].append(
                                        student_exam
                                    )
                                    student_exam_dates[student_id].append(current_date)

                                # Update slot usage
                                slot_seats_usage[slot_name] += len(student_ids)

                                # Remove this group from remaining groups
                                remove_scheduled_group(
                                    remaining_groups, course_id, group_id
                                )

                                print(
                                    f"  ✓ Scheduled course {course_id}, group {group_id} at {start_time}-{end_time}"
                                )

                            except Exception as e:
                                print(
                                    f"  ✗ Failed to create exam for course {course_id}, group {group_id}: {str(e)}"
                                )
                                logger.error(f"Failed to create exam: {str(e)}")
                                group_fully_scheduled = False
                        else:
                            unscheduled_reasons[group_id]=  f"  ✗ Not enough seats for course {course_id}, group {group_id} in {slot_name} slot"
                            print(
                                f"  ✗ Not enough seats for course {course_id}, group {group_id} in {slot_name} slot"
                            )
                            print(
                                f"    Required: {len(student_ids)}, Available: {all_available_seats - slot_seats_usage[slot_name]}"
                            )
                            group_fully_scheduled = False

                # Clean up empty courses from this group
                clean_empty_courses_from_group(remaining_groups[group_idx])

                # Check if group was fully scheduled
                if not group_fully_scheduled or remaining_groups[group_idx]["courses"]:
                    # Some parts of the group couldn't be scheduled
                    if remaining_groups[group_idx]["courses"]:
                        unscheduled_groups.append(remaining_groups[group_idx])
                        for course in remaining_groups[group_idx]["courses"]:
                            for group in course["groups"]:


                                unscheduled_reasons[group]=    f"  ! Group {group_idx + 1} partially scheduled - some courses remain"
                        print(
                            f"  ! Group {group_idx + 1} partially scheduled - some courses remain"
                        )
                    else:
                        print(
                            f"  ! Group {group_idx + 1} had scheduling issues but no courses remain"
                        )
                else:
                    print(f"  ✓ Group {group_idx + 1} fully scheduled")

                # Move to next date for next group
                date_index += 1

            # Allocate rooms (assuming this function exists)
            try:
                unaccommodated_students = allocate_shared_rooms(master_timetable.location.id)
            except Exception as e:
                print(f"Error in room allocation: {str(e)}")
                unaccommodated_students = []

        print(f"\nScheduling Summary:")
        print(f"  Total exams created: {len(exams_created)}")
        print(f"  Unscheduled groups: {len(unscheduled_groups)}")
        print("Groups: ", compatible_groups)
        pprint(unscheduled_reasons)
        return exams_created, unaccommodated_students, unscheduled_groups, unscheduled_reasons

    except Exception as e:
        print(f"Error generating schedule: {str(e)}")
        logger.error(f"Error generating schedule: {str(e)}")
        return [], f"Error generating schedule: {str(e)}", []


 
def allocate_shared_rooms_updated(student_exams):
    

    if not student_exams:
        return []
    location= student_exams[0].exam.group.course.department.location
    rooms = list(Room.objects.filter(location=location).order_by("-capacity"))
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
                if se.exam.slot_name==slot_name:
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

                            sem1 = int(exam1.group.course.semester.name.split()[1])
                            sem2 = int(exam2.group.course.semester.name.split()[1])

                            if abs(sem1 - sem2) > 1:
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
                        smallest_exam, students = min(
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
                    if se.exam.slot_name==slot_name:
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



def allocate_shared_rooms(location_id):
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
                if se.exam.slot_name==slot_name:
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

                            # sem1 = int(exam1.group.course.semester.name.split()[1])
                            # sem2 = int(exam2.group.course.semester.name.split()[1])
                            course1=exam1.group.course.id
                            course2= exam2.group.course.id

                            if course1!=course2:
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


 
 
def verify_day_off_constraints(min_gap_days=1):
    """
    Verify that the current schedule maintains day-off constraints
    """
    violations = []

    # Get all student exam dates
    student_exam_dates = defaultdict(list)
    for student_exam in StudentExam.objects.select_related("student", "exam"):
        student_exam_dates[student_exam.student.id].append(student_exam.exam.date)

    # Check each student's schedule
    for student_id, exam_dates in student_exam_dates.items():
        if len(exam_dates) < 2:
            continue

        sorted_dates = sorted(exam_dates)
        for i in range(len(sorted_dates) - 1):
            gap = (sorted_dates[i + 1] - sorted_dates[i]).days
            if gap < min_gap_days:
                violations.append(
                    f"Student {student_id}: {gap} day gap between {sorted_dates[i]} and {sorted_dates[i + 1]}"
                )

    return violations


def are_semesters_compatible(exam1, exam2):
    # Returns True if semesters have a gap of at least 2
    return (
        abs(
            int(exam1.course.semester.name.split(" ")[1])
            - int(exam2.course.semester.name.split(" ")[1])
        )
        > 1
    )


def allocate_single_exam_rooms(exam):
    """
    Allocate students to rooms for a single exam
    Returns a list of students who couldn't be accommodated
    """
    rooms = list(Room.objects.order_by("-capacity"))

    if not rooms:
        raise Exception("No rooms available for allocation.")

    student_exam_qs = StudentExam.objects.filter(exam=exam).select_related("student")
    unassigned = list(student_exam_qs)

    # Shuffle students to prevent friends from sitting together
    random.shuffle(unassigned)

    total_students = len(unassigned)
    available_capacity = sum(r.capacity for r in rooms)
    unaccommodated_students = []

    # Handle case where we don't have enough room capacity
    if total_students > available_capacity:
        accommodated_count = available_capacity
        unaccommodated_students = [se.student for se in unassigned[accommodated_count:]]
        unassigned = unassigned[:accommodated_count]

    # Assign students to rooms
    for room in rooms:
        if not unassigned:
            break

        chunk = unassigned[: room.capacity]
        for se in chunk:
            se.room = room
            se.save(update_fields=["room"])

        unassigned = unassigned[room.capacity :]

    return unaccommodated_students


def cancel_exam(exam_id):
    """
    Cancel a scheduled exam
    Returns True if successful
    """
    with transaction.atomic():
        StudentExam.objects.filter(exam_id=exam_id).delete()
        Exam.objects.filter(id=exam_id).delete()

    return True


def reschedule_exam(exam_id, new_date, slot=None):
    """
    Reschedule an exam to a new date and/or time with comprehensive validation
    Checks ALL constraints: student conflicts, room capacity, Friday slots, etc.
    Returns the updated exam instance
    """
    with transaction.atomic():
        exam = Exam.objects.get(id=exam_id)

        # Store original values for rollback if needed
        original_date = exam.date
        original_start_time = exam.start_time
        original_end_time = exam.end_time

        # 1. VALIDATE DAY OF WEEK
        weekday = new_date.strftime("%A")
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")

        # 2. VALIDATE AND SET TIME SLOT
        new_start_time = exam.start_time  # Default to current time
        new_end_time = exam.end_time

        if slot:
            # Friday slot validation
            if weekday == "Friday":
                available_slots = FRIDAY_SLOTS
            else:
                available_slots = SLOTS

            slot_match = next(
                (s for s in available_slots if s[0].lower() == slot.lower()), None
            )
            if not slot_match:
                available_slot_names = [s[0] for s in available_slots]
                raise ValueError(
                    f"Invalid slot '{slot}' for {weekday}. "
                    f"Available slots: {', '.join(available_slot_names)}"
                )

            _, new_start_time, new_end_time = slot_match
        else:
            # If no slot specified, validate current time slot is valid for the new day
            if weekday == "Friday":
                # Check if current time slot is valid for Friday
                current_slot = (exam.start_time, exam.end_time)
                friday_times = [(start, end) for _, start, end in FRIDAY_SLOTS]

                if current_slot not in friday_times:
                    available_slots = [
                        f"{label} ({start}-{end})" for label, start, end in FRIDAY_SLOTS
                    ]
                    raise ValueError(
                        f"Current time slot is not valid for Friday. "
                        f"Available Friday slots: {', '.join(available_slots)}. "
                        f"Please specify a valid slot."
                    )

        # 3. CHECK STUDENT CONFLICTS
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        conflicted_students = []

        for enrollment in enrolled_students:
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student, exam__date=new_date
            ).exclude(exam_id=exam_id)

            if existing_exams.exists():
                conflicted_students.append(
                    {
                        "student": enrollment.student.reg_no,
                        "conflicting_exams": [
                            se.exam.course.title for se in existing_exams
                        ],
                    }
                )

        if conflicted_students:
            conflict_details = []
            for conflict in conflicted_students[:3]:
                courses = ", ".join(conflict["conflicting_exams"])
                conflict_details.append(
                    f"{conflict['student']} (conflicts with: {courses})"
                )

            error_msg = f"Student conflicts found: {'; '.join(conflict_details)}"
            if len(conflicted_students) > 3:
                error_msg += f" ... and {len(conflicted_students) - 3} more students"

            raise ValueError(error_msg)

        # 4. CHECK ROOM CAPACITY CONFLICTS
        # Get number of students for this exam
        exam_student_count = Enrollment.objects.filter(course=exam.course).count()

        # Check existing exams in the same time slot
        existing_slot_exams = Exam.objects.filter(
            date=new_date, start_time=new_start_time, end_time=new_end_time
        ).exclude(id=exam_id)

        # Calculate total students that would need accommodation in this slot
        total_students_needed = exam_student_count
        other_exams_students = 0

        for other_exam in existing_slot_exams:
            other_exam_students = Enrollment.objects.filter(
                course=other_exam.course
            ).count()
            other_exams_students += other_exam_students
            total_students_needed += other_exam_students

        # Check available room capacity
        total_room_capacity = get_total_room_capacity()

        if total_students_needed > total_room_capacity:
            raise ValueError(
                f"Insufficient room capacity. Required: {total_students_needed} students, "
                f"Available: {total_room_capacity} seats. "
                f"This exam needs {exam_student_count} seats, "
                f"other exams in this slot need {other_exams_students} seats."
            )

        # 5. CHECK FOR COURSE COMPATIBILITY CONFLICTS
        # Ensure courses scheduled together don't share students
        if existing_slot_exams:
            exam_students = set(
                Enrollment.objects.filter(course=exam.course).values_list(
                    "student_id", flat=True
                )
            )

            for other_exam in existing_slot_exams:
                other_students = set(
                    Enrollment.objects.filter(course=other_exam.course).values_list(
                        "student_id", flat=True
                    )
                )

                common_students = exam_students.intersection(other_students)
                if common_students:
                    common_count = len(common_students)
                    raise ValueError(
                        f"Course compatibility conflict: {common_count} student(s) are enrolled in both "
                        f"'{exam.course.name}' and '{other_exam.course.name}'. "
                        f"These courses cannot be scheduled in the same time slot."
                    )

        # 6. VALIDATE ROOM ALLOCATION FEASIBILITY
        # Check if we can actually allocate rooms for all courses in this slot
        if existing_slot_exams:
            # Simulate room allocation
            all_slot_exams = list(existing_slot_exams) + [exam]
            room_requirements = []

            for slot_exam in all_slot_exams:
                student_count = Enrollment.objects.filter(
                    course=slot_exam.course
                ).count()
                room_requirements.append(student_count)

            # Check if we can fit all exams in available rooms
            rooms = list(Room.objects.order_by("-capacity"))
            if not can_accommodate_exams(room_requirements, rooms):
                raise ValueError(
                    f"Cannot allocate rooms efficiently for all exams in this slot. "
                    f"Room allocation would fail with current room configuration."
                )

        # 7. UPDATE EXAM AND HANDLE ROOM REALLOCATION
        exam.date = new_date
        exam.start_time = new_start_time
        exam.end_time = new_end_time
        exam.save()

        # 8. REALLOCATE ROOMS FOR THIS TIME SLOT
        # Get all exams in the new time slot (including the rescheduled one)
        slot_exams = list(
            Exam.objects.filter(
                date=new_date, start_time=new_start_time, end_time=new_end_time
            )
        )

        # Clear existing room assignments for this slot
        StudentExam.objects.filter(exam__in=slot_exams).update(room=None)

        # Reallocate rooms
        try:
            unaccommodated = allocate_shared_rooms(slot_exams)
            if unaccommodated:
                # Rollback the exam changes
                exam.date = original_date
                exam.start_time = original_start_time
                exam.end_time = original_end_time
                exam.save()

                raise ValueError(
                    f"Room allocation failed: {len(unaccommodated)} students could not be accommodated. "
                    f"Exam rescheduling has been cancelled."
                )
        except Exception as e:
            # Rollback on any room allocation error
            exam.date = original_date
            exam.start_time = original_start_time
            exam.end_time = original_end_time
            exam.save()
            raise ValueError(f"Room allocation error: {str(e)}")

    return exam


def can_accommodate_exams(student_counts, rooms):
    """
    Check if given student counts can be accommodated in available rooms
    Uses a simple bin-packing approach
    """
    if not rooms:
        return False

    total_students = sum(student_counts)
    total_capacity = sum(room.capacity for room in rooms)

    if total_students > total_capacity:
        return False

    # Simple greedy allocation check
    sorted_counts = sorted(student_counts, reverse=True)
    sorted_rooms = sorted(rooms, key=lambda r: r.capacity, reverse=True)

    # Try to fit largest student groups in largest rooms
    room_remaining = [room.capacity for room in sorted_rooms]

    for count in sorted_counts:
        # Find a room that can accommodate this count
        allocated = False
        for i, remaining in enumerate(room_remaining):
            if remaining >= count:
                room_remaining[i] -= count
                allocated = True
                break

        if not allocated:
            return False

    return True


def get_reschedule_suggestions(exam_id, preferred_date_range=7):
    """
    Get suggestions for rescheduling an exam
    Returns available slots within the preferred date range
    """
    exam = Exam.objects.get(id=exam_id)
    current_date = exam.date

    # Look for available slots within the date range
    start_search = current_date - timedelta(days=preferred_date_range)
    end_search = current_date + timedelta(days=preferred_date_range)

    suggestions = []
    current = start_search

    while current <= end_search:
        if current == exam.date:
            current += timedelta(days=1)
            continue

        weekday = current.strftime("%A")
        if weekday in NO_EXAM_DAYS:
            current += timedelta(days=1)
            continue

        # Get available slots for this day
        available_slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS

        for slot_name, start_time, end_time in available_slots:
            try:
                # Test if this slot would work (without actually rescheduling)
                test_conflicts = check_reschedule_feasibility(
                    exam_id, current, slot_name
                )
                if not test_conflicts:
                    suggestions.append(
                        {
                            "date": current,
                            "slot": slot_name,
                            "start_time": start_time,
                            "end_time": end_time,
                            "weekday": weekday,
                        }
                    )
            except:
                continue  # Skip this slot if it has issues

        current += timedelta(days=1)

    return suggestions


def check_reschedule_feasibility(exam_id, new_date, slot_name):
    """
    Check if rescheduling is feasible without actually doing it
    Returns list of conflicts/issues, empty list if feasible
    """
    conflicts = []

    try:
        exam = Exam.objects.get(id=exam_id)
        weekday = new_date.strftime("%A")

        # Check day validity
        if weekday in NO_EXAM_DAYS:
            conflicts.append(f"Cannot schedule on {weekday}")
            return conflicts

        # Check slot validity
        available_slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS
        slot_match = next(
            (s for s in available_slots if s[0].lower() == slot_name.lower()), None
        )
        if not slot_match:
            conflicts.append(f"Invalid slot '{slot_name}' for {weekday}")
            return conflicts

        _, new_start_time, new_end_time = slot_match

        # Check student conflicts
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        student_conflicts = 0

        for enrollment in enrolled_students:
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student, exam__date=new_date
            ).exclude(exam_id=exam_id)

            if existing_exams.exists():
                student_conflicts += 1

        if student_conflicts > 0:
            conflicts.append(f"{student_conflicts} student conflicts")

        # Check room capacity
        exam_students = Enrollment.objects.filter(course=exam.course).count()
        existing_slot_exams = Exam.objects.filter(
            date=new_date, start_time=new_start_time, end_time=new_end_time
        ).exclude(id=exam_id)

        total_students = exam_students
        for other_exam in existing_slot_exams:
            total_students += Enrollment.objects.filter(
                course=other_exam.course
            ).count()

        total_capacity = get_total_room_capacity()
        if total_students > total_capacity:
            conflicts.append(
                f"Insufficient capacity ({total_students} needed, {total_capacity} available)"
            )

    except Exception as e:
        conflicts.append(f"Error checking feasibility: {str(e)}")

    return conflicts


def get_unaccommodated_students():
    """
    Get a list of students who couldn't be accommodated in the exam schedule
    """
    # Students without a room assignment
    unaccommodated = StudentExam.objects.filter(room__isnull=True).select_related(
        "student", "exam__course"
    )

    result = []
    for student_exam in unaccommodated:
        result.append(
            {
                "student": student_exam.student,
                "course": student_exam.exam.course,
                "exam_date": student_exam.exam.date,
                "exam_slot": (student_exam.exam.start_time, student_exam.exam.end_time),
            }
        )

    return result


def verify_exam_schedule():
    """
    Verify that the current exam schedule has no conflicts
    Returns a list of any conflicts found
    """
    conflicts = []

    # Check for students with multiple exams in one day
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related("student", "exam"):
        student_exams[student_exam.student.id].append(student_exam)

    for student_id, exams in student_exams.items():
        exams_by_date = defaultdict(list)
        for exam in exams:
            exams_by_date[exam.exam.date].append(exam)

        for date, day_exams in exams_by_date.items():
            if len(day_exams) > 1:
                conflicts.append(
                    {
                        "type": "multiple_exams_per_day",
                        "student_id": student_id,
                        "date": date,
                        "exams": [e.exam.id for e in day_exams],
                    }
                )

    # Check for room overallocation
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.all():
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)

    for slot, slot_exams in exams_by_slot.items():
        room_student_counts = defaultdict(lambda: defaultdict(int))

        for exam in slot_exams:
            student_exams = StudentExam.objects.filter(exam=exam).select_related("room")
            for se in student_exams:
                if se.room:
                    room_student_counts[se.room.id][exam.id] += 1

        for room_id, exam_counts in room_student_counts.items():
            room = Room.objects.get(id=room_id)
            total_students = sum(exam_counts.values())

            if total_students > room.capacity:
                conflicts.append(
                    {
                        "type": "room_overallocation",
                        "room_id": room_id,
                        "capacity": room.capacity,
                        "allocated": total_students,
                        "slot": slot,
                        "exams": list(exam_counts.keys()),
                    }
                )

    # Check for courses in same slot without being in same group
    # (they shouldn't share any students)
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.all():
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)

    for slot, slot_exams in exams_by_slot.items():
        # Skip slots with only one exam
        if len(slot_exams) < 2:
            continue

        # For each pair of exams in this slot, check if they share students
        for i, exam1 in enumerate(slot_exams):
            for exam2 in slot_exams[i + 1 :]:
                # Check if these exams share any students
                students1 = set(
                    Enrollment.objects.filter(course=exam1.course).values_list(
                        "student_id", flat=True
                    )
                )
                students2 = set(
                    Enrollment.objects.filter(course=exam2.course).values_list(
                        "student_id", flat=True
                    )
                )

                common_students = students1.intersection(students2)
                if common_students:
                    conflicts.append(
                        {
                            "type": "student_exam_conflict",
                            "course1": exam1.course.id,
                            "course2": exam2.course.id,
                            "common_students": list(common_students),
                            "slot": slot,
                        }
                    )

    return conflicts
