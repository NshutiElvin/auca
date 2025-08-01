from datetime import timedelta, time
from collections import defaultdict
import random
from django.db import transaction
from django.utils.timezone import now
from django.db.models import Sum

from courses.models import Course, CourseGroup
from exams.models import Exam, StudentExam
from enrollments.models import Enrollment
from rooms.models import Room
from django.db.models import Count
from pprint import pprint
import logging
from datetime import time
from collections import defaultdict
from django.db import transaction
from django.db.models import Count
from collections import defaultdict, deque
import heapq


from collections import defaultdict
from itertools import combinations

logger = logging.getLogger(__name__)
GROUP_PREFERENCES = {
    "A": "mostly morning",
    "B": "mostly morning", 
    "C": "mixed",
    "D": "mixed",
    "E": "evening",
    "F": "evening"
}

SLOTS = [
    ('Morning', time(8, 0), time(11, 0)),
    ('Afternoon', time(13, 0), time(16, 0)),
    ('Evening', time(17, 0), time(20, 0)),
]
FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]   
NO_EXAM_DAYS = ['Saturday']   
 

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
            for course2 in courses[i+1:]:
                course_pair = tuple(sorted([course1, course2]))
                conflict_matrix[course_pair] += 1
    
    return conflict_matrix

def find_compatible_courses(course_conflict_matrix):
    
    all_courses = set()
    for course1, course2 in course_conflict_matrix.keys():
        all_courses.add(course1)
        all_courses.add(course2)
    enrolled_courses = Course.objects.annotate(
         enrollment_count=Count('enrollments')
        ).filter(enrollment_count__gt=0)
    
    for course in enrolled_courses.values_list('id', flat=True):
        all_courses.add(course)
    
    compatibility_graph = {course: set() for course in all_courses}
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if pair not in course_conflict_matrix or course_conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    remaining_courses = set(all_courses)
    course_groups = []
    
    while remaining_courses:
        course_group = []
        
        if remaining_courses:
            course1 = min(
                [c for c in remaining_courses],
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) \
                    if len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) > 0 \
                    else float('inf')
            )
            
            course_group.append(course1)
            remaining_courses.remove(course1)
            
            compatible_with_group = set(compatibility_graph[course1]) & remaining_courses
            
            while compatible_with_group:  
                # Select the course with fewest remaining compatible options (to save harder-to-place courses for later)
                next_course = min(
                    compatible_with_group,
                    key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
                )
                
                course_group.append(next_course)
                remaining_courses.remove(next_course)
                
                # Update the set of courses compatible with the entire group
                compatible_with_group &= set(compatibility_graph[next_course])
                compatible_with_group &= remaining_courses
        
        if course_group:
            course_groups.append(course_group)
    
    return course_groups

def get_exam_slots(start_date,end_date, max_slots=None):
  
    date_slots = []
    current_date = start_date
    

    while current_date <= end_date :
        weekday = current_date.strftime('%A')
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
                if max_slots and len(date_slots) >= max_slots:
                    break
        current_date += timedelta(days=1)

    return date_slots


def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0
 

 

def get_course_group(course):
    """
    Extract the group from course name (assuming format like "Course A", "Course B", etc.)
    You may need to modify this based on your actual course naming convention
    """
    # This is a placeholder - adjust based on your actual course model structure
    # Option 1: If course has a group field
    if hasattr(course, 'group'):
        return course.group
    
    # Option 2: If group is in course name
    course_name = course.name or course.title
    if course_name:
        # Extract last character as group (adjust as needed)
        group_char = course_name.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char
    
    # Option 3: If course code contains group info
    if hasattr(course, 'code') and course.code:
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
        enrollment_count=Count('enrollments')
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

# def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
#     """Determine which slot is good for students, so that they can't do more than 2 exam in same slot. even if it is exception
#     Restrictions: No exams on Saturday, No evening exams on Friday"""
#     from django.db.models import Min, Max  # Import for finding exam period boundaries
#     # Check if the requested date is valid for scheduling
#     day_of_week = date.weekday()  # Monday=0, Sunday=6
    
#     # Saturday restriction (weekday 5 = Saturday)
#     if day_of_week == 5:  # Saturday
#         return new_group, None, {"No exams can be scheduled on Saturday"}
    
#     # Friday evening restriction (weekday 4 = Friday)
#     if day_of_week == 4 and suggested_slot == "Evening":  # Friday
#         suggested_slot = "Morning"  # Default to morning if evening was suggested on Friday
    
#     to_days_exams = Exam.objects.filter(date=date)
#     enrolled_students_new_group = Enrollment.objects.filter(group_id__in=new_group).values_list('student_id', flat=True)
 
#     # classify the exams into slots
#     slots_with_exams = {"Morning": [], "Afternoon": [], "Evening": []}
#     for exam in to_days_exams:
#         if exam.start_time == time(8, 0):
#             slots_with_exams["Morning"].append(exam.group.id)
#         elif exam.start_time == time(13, 0):
#             slots_with_exams["Afternoon"].append(exam.group.id)
#         elif exam.start_time == time(18, 0):
#             slots_with_exams["Evening"].append(exam.group.id)

#     conflicts = {"Morning": [], "Afternoon": [], "Evening": []}
#     todays_suggestions = set()
#     todays_slot_suggestion = None
#     other_slot_suggestion = None
#     slots_with_students = {
#         "Morning": Enrollment.objects.filter(
#             group__in=slots_with_exams["Morning"]
#         ).values_list('student_id', flat=True), 
#         "Afternoon": Enrollment.objects.filter(
#             group__in=slots_with_exams["Afternoon"]
#         ).values_list('student_id', flat=True), 
#         "Evening": Enrollment.objects.filter(
#             group__in=slots_with_exams["Evening"]
#         ).values_list('student_id', flat=True)
#     }
    
#     # check if the suggested slot already has conflict
#     for student in enrolled_students_new_group:
#         if suggested_slot == "Morning":
#             if student in slots_with_students['Morning']:
#                 conflicts['Morning'].append(f"Student {student} already has an exam of {get_student_exam(student, date, time(8, 0)).exam.group.course.title} in the morning slot.")
#         elif suggested_slot == "Afternoon":
#             if student in slots_with_students['Afternoon']:
#                 conflicts['Afternoon'].append(f"Student {student} already has an exam of {get_student_exam(student, date, time(13, 0)).exam.group.course.title} in the afternoon slot.")
#         elif suggested_slot == "Evening":
#             if student in slots_with_students["Evening"]:
#                 conflicts['Evening'].append(f"Student {student} already has an exam of {get_student_exam(student, date, time(18, 0)).exam.group.course.title} in the evening slot.")
    
#     # check if the suggested slot has conflict - Fixed logic error
#     suggested_slot_has_conflict = True if len(conflicts[suggested_slot]) > 0 else False
    
#     if suggested_slot_has_conflict:
#         todays_suggestions.add(f"The suggested slot {suggested_slot} is not available because it has conflict")
#     else:
#         total_slots_students = len(enrolled_students_new_group) + len(slots_with_students[suggested_slot])
#         if check_rooms_availability_for_slots(total_slots_students):
#             todays_slot_suggestion = {"date": date, "slot": suggested_slot}
#             todays_suggestions.add(f"The suggested slot {str(date)} {suggested_slot} is available")  # Fixed message
#         else:
#             todays_suggestions.add(f"The suggested slot {str(date)} {suggested_slot} is not available because it hasn't enough rooms")
    
#     # if the suggested slot has conflict, then we need to find another slot
#     available_slots = ["Morning", "Afternoon", "Evening"]
    
#     # Remove evening slot if it's Friday
#     if day_of_week == 4:  # Friday
#         available_slots = ["Morning", "Afternoon"]
    
#     for slot in available_slots:
#         if slot == suggested_slot:
#             continue
#         # check if the slot has conflict - Fixed logic error
#         slot_has_conflict = True if len(conflicts[slot]) > 0 else False
#         total_slots_students = len(enrolled_students_new_group) + len(slots_with_students[slot])
#         if slot_has_conflict:
#             todays_suggestions.add(f"The {date} {slot} slot is not available because it has conflict")
#         else:
#             if check_rooms_availability_for_slots(total_slots_students):
#                 if not todays_slot_suggestion:  # Only set if we don't already have a suggestion
#                     todays_slot_suggestion = {"date": date, "slot": slot}
#                 todays_suggestions.add(f"The {date} {slot} slot is available")
#             else:
#                 todays_suggestions.add(f"The {date} {slot} slot is not available because it hasn't enough rooms")
    
#     if todays_slot_suggestion:
#         return new_group, todays_slot_suggestion, todays_suggestions
#     else:
#         # find in other days where new group can be scheduled
#         # Get the exam period boundaries
#         exam_dates = Exam.objects.aggregate(
#             min_date=Min('date'),
#             max_date=Max('date')
#         )
        
#         if exam_dates['min_date'] and exam_dates['max_date']:
#             # Start search from the beginning of exam period, but not before the requested date
#             start_date = max(exam_dates['min_date'], date + timedelta(days=1))
            
#             # Also consider dates within the exam period that might not have exams yet
#             exam_period_end = exam_dates['max_date']
#         else:
#             # If no exams exist yet, start from the day after requested date
#             start_date = date + timedelta(days=1)
#             exam_period_end = start_date + timedelta(days=14)  # Default 2-week period
            
#         other_days_exams = Exam.objects.filter(date__gte=start_date).order_by('date')
        
#         # Get unique dates from future exams within the exam period
#         future_dates = other_days_exams.values_list('date', flat=True).distinct()
        
#         # Also include dates within exam period that might not have exams scheduled yet
#         all_potential_dates = set(future_dates)
        
#         # Add dates between start_date and exam_period_end that don't have exams
#         current_date = start_date
#         while current_date <= exam_period_end and len(all_potential_dates) < 20:  # Limit to prevent infinite loop
#             if current_date.weekday() != 5:  # Skip Saturdays
#                 all_potential_dates.add(current_date)
#             current_date += timedelta(days=1)
        
#         # Sort dates for systematic checking
#         sorted_dates = sorted(all_potential_dates)
        
#         # Check up to reasonable number of days or until we find a suitable slot
#         max_days_to_check = min(len(sorted_dates), 14)
#         days_checked = 0
        
#         for future_date in sorted_dates:
#             if days_checked >= max_days_to_check:
#                 break
            
#             # Check if future date is valid for scheduling
#             future_day_of_week = future_date.weekday()
            
#             # Skip Saturday
#             if future_day_of_week == 5:  # Saturday
#                 days_checked += 1
#                 continue
                
#             future_date_exams = Exam.objects.filter(date=future_date)
            
#             # classify future date exams into slots
#             future_slots_with_exams = {"Morning": [], "Afternoon": [], "Evening": []}
#             for exam in future_date_exams:
#                 if exam.start_time == time(8, 0):
#                     future_slots_with_exams["Morning"].append(exam.group.id)
#                 elif exam.start_time == time(13, 0):
#                     future_slots_with_exams["Afternoon"].append(exam.group.id)
#                 elif exam.start_time == time(18, 0):
#                     future_slots_with_exams["Evening"].append(exam.group.id)
            
#             future_slots_with_students = {
#                 "Morning": Enrollment.objects.filter(
#                     group__in=future_slots_with_exams["Morning"]
#                 ).values_list('student_id', flat=True), 
#                 "Afternoon": Enrollment.objects.filter(
#                     group__in=future_slots_with_exams["Afternoon"]
#                 ).values_list('student_id', flat=True), 
#                 "Evening": Enrollment.objects.filter(
#                     group__in=future_slots_with_exams["Evening"]
#                 ).values_list('student_id', flat=True)
#             }
            
#             # Check each slot on this future date
#             future_available_slots = ["Morning", "Afternoon", "Evening"]
            
#             # Remove evening slot if it's Friday
#             if future_day_of_week == 4:  # Friday
#                 future_available_slots = ["Morning", "Afternoon"]
            
#             for slot in future_available_slots:
#                 has_conflict = False
#                 for student in enrolled_students_new_group:
#                     if student in future_slots_with_students[slot]:
#                         has_conflict = True
#                         break
                
#                 if not has_conflict:
#                     total_students = len(enrolled_students_new_group) + len(future_slots_with_students[slot])
#                     if check_rooms_availability_for_slots(total_students):
#                         other_slot_suggestion = {"date": future_date, "slot": slot}
#                         break
            
#             if other_slot_suggestion:
#                 break
                
#             days_checked += 1
        
#         # If no slot found in existing exam days, suggest the next available day
#         if not other_slot_suggestion:
#             # Try to find a completely free day within the next week (excluding Saturdays)
#             for i in range(1, 8):
#                 test_date = date + timedelta(days=i)
#                 test_day_of_week = test_date.weekday()
                
#                 # Skip Saturday
#                 if test_day_of_week == 5:  # Saturday
#                     continue
                
#                 if not Exam.objects.filter(date=test_date).exists():
#                     # This date has no exams, so any valid slot would work
#                     test_slot = suggested_slot
                    
#                     # If it's Friday and suggested slot is evening, use morning instead
#                     if test_day_of_week == 4 and suggested_slot == "Evening":  # Friday
#                         test_slot = "Morning"
                    
#                     if check_rooms_availability_for_slots(len(enrolled_students_new_group)):
#                         other_slot_suggestion = {"date": test_date, "slot": test_slot}
#                         break
            
#             # If still no suggestion, find next valid day with preferred slot
#             if not other_slot_suggestion:
#                 for i in range(1, 15):  # Extended search range
#                     test_date = date + timedelta(days=i)
#                     test_day_of_week = test_date.weekday()
                    
#                     # Skip Saturday
#                     if test_day_of_week == 5:  # Saturday
#                         continue
                    
#                     test_slot = suggested_slot
                    
#                     # If it's Friday and suggested slot is evening, use morning instead
#                     if test_day_of_week == 4 and suggested_slot == "Evening":  # Friday
#                         test_slot = "Morning"
                    
#                     other_slot_suggestion = {"date": test_date, "slot": test_slot}
#                     break
        
#         other_suggestions = {f"Alternative suggestion: {other_slot_suggestion['date']} {other_slot_suggestion['slot']} slot"}
        
#         return new_group, other_slot_suggestion, todays_suggestions.union(other_suggestions)



def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
    """Determine which slot is good for students, so that they can't do more than 2 exam in same slot. even if it is exception
    Restrictions: No exams on Saturday, No evening exams on Friday
    Returns: tuple of (new_group, best_slot_suggestion, all_suggestions, all_conflicts)"""
    from django.db.models import Min, Max
    from datetime import timedelta, time
    from collections import defaultdict

    # Initialize data structures
    all_suggestions = []
    all_conflicts = defaultdict(list)
    possible_slots = []

    # Check if the requested date is valid for scheduling
    day_of_week = date.weekday()  # Monday=0, Sunday=6
    
    # Saturday restriction
    if day_of_week == 5:  # Saturday
        all_conflicts["Saturday"].append("No exams can be scheduled on Saturday")
        return new_group, None, all_suggestions, all_conflicts
    
    # Friday evening restriction
    if day_of_week == 4 and suggested_slot == "Evening":  # Friday
        suggested_slot = "Morning"  # Default to morning if evening was suggested on Friday
    
    enrolled_students_new_group = Enrollment.objects.filter(group_id__in=new_group).values_list('student_id', flat=True)
 
    # Function to check conflicts for a given date and slot
    def check_slot_conflicts(check_date, slot):
        slot_exams = Exam.objects.filter(date=check_date, 
                                       start_time=time(8, 0) if slot == "Morning" else 
                                       (time(13, 0) if slot == "Afternoon" else time(18, 0)))
        slot_groups = [exam.group.id for exam in slot_exams]
        slot_students = Enrollment.objects.filter(group__in=slot_groups).values_list('student_id', flat=True)
        
        conflicts = []
        for student in enrolled_students_new_group:
            if student in slot_students:
                exam = slot_exams.filter(group__enrollment__student_id=student).first()
                conflicts.append(f"Student {student} already has an exam of {exam.group.course.title} in the {slot} slot on {check_date}")
        
        return conflicts, len(slot_students)

    # Function to evaluate a date and slot combination
    def evaluate_slot(check_date, slot, is_suggested=False):
        conflicts, student_count = check_slot_conflicts(check_date, slot)
        total_students = len(enrolled_students_new_group) + student_count
        
        if conflicts:
            conflict_msg = f"{check_date} {slot} slot has conflicts"
            all_conflicts[check_date].extend(conflicts)
            if is_suggested:
                all_suggestions.append({"suggested":False,"date": check_date, "slot": slot, "reason": f"Suggested slot {check_date} {slot} is not available (conflicts)"})
            else:
                all_suggestions.append({"suggested":False,"date": check_date, "slot": slot, "reason": f"Slot {check_date} {slot} is not available (conflicts)"})
            return False
        elif not check_rooms_availability_for_slots(total_students):
            room_msg = f"{check_date} {slot} slot lacks room capacity"
            all_conflicts[check_date].append(room_msg)
            if is_suggested:
                all_suggestions.append({"suggested":False,"date": check_date, "slot": slot, "reason": f"Suggested slot {check_date} {slot} is not available (insufficient rooms)"})
            else:
                all_suggestions.append({"suggested":False,"date": check_date, "slot": slot, "reason": f"Slot {check_date} {slot} is not available (insufficient rooms)"})
            return False
        else:
            msg = {"suggested":True,"date": check_date, "slot": slot, "reason": f"Slot {check_date} {slot} is available"}
            all_suggestions.append(msg)
            possible_slots.append({"date": check_date, "slot": slot})
            return True

    # Check suggested slot first
    evaluate_slot(date, suggested_slot, is_suggested=True)

    # Check other slots on the same day
    available_slots = ["Morning", "Afternoon", "Evening"]
    if day_of_week == 4:  # Friday
        available_slots.remove("Evening")
    
    for slot in available_slots:
        if slot != suggested_slot:
            evaluate_slot(date, slot)

    # Check past dates (up to 7 days before)
    min_exam_date = Exam.objects.aggregate(Min('date'))['date__min']
    max_exam_date = Exam.objects.aggregate(Max('date'))['date__max']
    for days_before in range(1, 8):
        past_date = date - timedelta(days=days_before)
        if past_date < min_exam_date:  # Don't check before the earliest exam date
            continue
        if past_date.weekday() == 5:  # Skip Saturday
            continue
        
        past_available_slots = ["Morning", "Afternoon", "Evening"]
        if past_date.weekday() == 4:  # Friday
            past_available_slots.remove("Evening")
        
        for slot in past_available_slots:
            evaluate_slot(past_date, slot)

    # Check future dates (up to 14 days after)
    for days_after in range(1, 15):
        future_date = date + timedelta(days=days_after)
        if future_date > max_exam_date:  # Don't check beyond the latest exam date
            continue
        if future_date.weekday() == 5:  # Skip Saturday
            continue
        
        future_available_slots = ["Morning", "Afternoon", "Evening"]
        if future_date.weekday() == 4:  # Friday
            future_available_slots.remove("Evening")
        
        for slot in future_available_slots:
            evaluate_slot(future_date, slot)

    # Determine best suggestion (prioritizing suggested date, then suggested slot, then earliest date)
    best_suggestion = None
    if possible_slots:
        # Try to find on the same date first
        same_date_slots = [s for s in possible_slots if s["date"] == date]
        if same_date_slots:
            # Try to find the suggested slot first
            suggested_slot_match = [s for s in same_date_slots if s["slot"] == suggested_slot]
            if suggested_slot_match:
                best_suggestion = suggested_slot_match[0]
            else:
                best_suggestion = same_date_slots[0]
        else:
            # Find the earliest possible date
            possible_slots.sort(key=lambda x: x["date"])
            best_suggestion = possible_slots[0]

    return new_group, best_suggestion, all_suggestions, all_conflicts
        


def get_slot_name(start_time, end_time):
    """
    Get the slot name based on start and end times
    """
    if start_time == time(8, 0) and end_time == time(11, 0):
        return "Morning"
    elif start_time == time(13, 0) and end_time == time(16, 0):
        return "Afternoon"
    elif start_time == time(17, 0) and end_time == time(20, 0):
        return "Evening"
    else:
        return None
    

def verify_groups_compatiblity(groups):

    course_group_students = defaultdict(lambda: defaultdict(list))
    for enrollment in Enrollment.objects.filter(group_id__in=groups).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].append(enrollment.student_id)
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
        if shared_students:  # Shared students exist
            group_conflicts.append((group1, group2, len(shared_students)))  # Add count of shared students
    return group_conflicts
    



def find_compatible_courses_within_group(courses):
    if not courses:
        return {
            'compatible_groups': [],
            'group_conflicts': defaultdict(list)
        }

    # Data structure: {course_id: {group_id: [student_ids]}}
    course_group_students = defaultdict(lambda: defaultdict(list))
    
    # Populate enrollment data
    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].append(enrollment.student_id)
    
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
        
        compatible_groups.append({
            'timeslot': color + 1,
            'courses': [
                {'course_id': course_id, 'groups': group_ids}
                for course_id, group_ids in course_map.items()
            ],
            'student_count': sum(
                len(course_group_students[course_id][group_id])
                for course_id, group_id in groups
            )
        })
    
    compatible_groups.sort(key=lambda x: -x['student_count'])
    return  compatible_groups,group_conflicts
    


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
    
    student_ids = Enrollment.objects.filter(course=course, group=group).values_list('student_id', flat=True)
    
    for student_id in student_ids:
        current_exam_dates = student_exam_dates.get(student_id, [])
        
        # Check for same-day conflict
        if proposed_date in current_exam_dates:
            conflicts.append(f"Student {student_id} already has exam on {proposed_date}")
            continue
        
        # Check for day-off constraint
        if not has_sufficient_gap(current_exam_dates, proposed_date):
            conflicts.append(f"Student {student_id} would not have sufficient gap")
    
    return len(conflicts) == 0, conflicts





def generate_exam_schedule(start_date=None, end_date=None,course_ids=None, semester=None):
 
    try:
        
        if not start_date:
            start_date = now().date() + timedelta(days=1)
        start_date+= timedelta(days=1)
        
        if course_ids:
            enrolled_courses = course_ids
        else:
            enrolled_courses = Course.objects.annotate(
                enrollment_count=Count('enrollments')
            ).filter(enrollment_count__gt=0)
        
        
        compatible_groups, _= find_compatible_courses_within_group(enrolled_courses)
        # random.shuffle(compatible_groups)
        if not compatible_groups:
            print("No compatible course groups found")
            return [], "No compatible course groups found"
        
        
        # Generate exam slots
        estimated_slots_needed = len(compatible_groups) *3
        
        date_slots = get_exam_slots(start_date, end_date,max_slots=estimated_slots_needed)
        slots_by_date = defaultdict(list)
        
        for slot_idx, (date, label, start, end) in enumerate(date_slots):
            slots_by_date[date].append((slot_idx, label, start, end))
        
        myscheduled_groups=[*compatible_groups]
        
        exams_created = []
        student_exam_dates = defaultdict(list)
        scheduled_exams_per_date= defaultdict(list)
        with transaction.atomic():
            dates = sorted(slots_by_date.keys())
            date_index=0
            for idx,course_group in enumerate(compatible_groups):
                if date_index >= len(dates) or len(myscheduled_groups)<=0:
                    break   
                    
                date = dates[date_index]
                weekday = date.strftime('%A')
                
                if weekday == "Saturday":
                    date_index += 1
                    continue
                
                    
                courses= course_group["courses"]
                
                for mycourse_group in courses:

                    course_id= mycourse_group["course_id"]
                    course_groups=mycourse_group["groups"]
                    course = Course.objects.get(id=course_id)
                    for group_id in course_groups:
                        group=CourseGroup.objects.get(id= group_id)
                        start_time = None
                        end_time = None
                        if group.group_name in ["A", "B"]:
                            toss= random.randint(1, 2)
                            start_time = None
                            end_time = None
                            if toss == 1:
                                start_time = time(8, 0)
                                end_time = time(11, 0)
                                slot = "Morning"
                            else:
                                start_time = time(13, 0)
                                end_time = time(16, 0)
                                slot = "Afternoon"
                             
                        elif group.group_name in ["C", "D"]:
                            if weekday == "Friday":
                                start_time = time(13, 0)
                                end_time = time(16, 0)
                                slot = "Afternoon"
                            else:
                                guess = random.randint(1, 3)
                                if guess == 1:
                                    start_time = time(8, 0)
                                    end_time = time(11, 0)
                                    slot = "Morning"
                                elif guess == 2:
                                    start_time = time(13, 0)
                                    end_time = time(16, 0)
                                    slot = "Afternoon"
                                else:
                                    start_time = time(18, 0)
                                    end_time = time(20, 0)
                                    slot = "Evening"
                        elif group.group_name in ["E", "F"]:
                            if weekday != "Friday":
                                start_time = time(18, 0)
                                end_time = time(20, 0)
                                slot = "Evening"
                            else:
                                start_time = time(13, 0)
                                end_time = time(16, 0)
                                slot = "Afternoon"
                        else:
                            start_time = time(13, 0)
                            end_time = time(16, 0)
                            slot = "Afternoon"

                        # Create the exam
                        try:
                            exam = Exam.objects.create(
                                date=date,
                                start_time=start_time,
                                end_time=end_time,
                                group=group
                            )
                            exams_created.append(exam)
                            
                            # Update student exam dates
                            student_ids = Enrollment.objects.filter(
                                course=course, group=group
                            ).values_list('student_id', flat=True)
                            for student_id in student_ids:
                                student_exam= StudentExam.objects.create(
                                    student_id=student_id,
                                    exam=exam

                                )
                                student_exam.save()
                                scheduled_exams_per_date[date].append(student_exam)
                                student_exam_dates[student_id].append(date)
                            
                        except Exception as e:
                            logger.error(f"Failed to create exam for course {course.id}: {str(e)}")
                            break
                myscheduled_groups.remove(course_group)
                date_index+=1
                
                 
            
        unaccommodated_students=allocate_shared_rooms()
        return exams_created, unaccommodated_students, myscheduled_groups
    
    except Exception as e:
        print(e)
        return [], f"Error generating schedule: {str(e)}"
from collections import defaultdict
from datetime import time
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

def allocate_shared_rooms():
    """
    Optimized exam room allocation using bin-packing approach.
    Prioritizes room sharing and maximizes space utilization.
    """
    # Get all unassigned student exams with related data
    student_exams = StudentExam.objects.filter(
        room__isnull=True
    ).select_related(
        'exam',
        'exam__group__course__semester',
        'student'
    ).order_by('exam__date', 'exam__start_time')
    
    if not student_exams.exists():
        return []

    # Step 2: Sort rooms by capacity (largest first)
    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    # Define time slots
    SLOTS = [
        ('Morning', time(8, 0), time(11, 0)),
        ('Afternoon', time(13, 0), time(16, 0)),
        ('Evening', time(18, 0), time(20, 0)),
    ]

    with transaction.atomic():
        # Data structure: {date: {slot: {room_id: RoomAllocation}}}
        schedule = defaultdict(lambda: defaultdict(dict))
        unaccommodated = []

        # Organize students by date and slot
        date_slot_exams = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        
        for se in student_exams:
            for slot_name, start, end in SLOTS:
                if se.exam.start_time == start and se.exam.end_time == end:
                    date_slot_exams[se.exam.date][slot_name][se.exam].append(se)
                    break

        # Process each date and slot
        for date, slots in date_slot_exams.items():
            for slot_name in ['Morning', 'Afternoon', 'Evening']:
                if slot_name not in slots:
                    continue
                    
                exams_dict = slots[slot_name]
                if not exams_dict:
                    continue

                # Step 1: Sort exam groups by student count (largest first)
                exam_groups = [(exam, students) for exam, students in exams_dict.items()]
                exam_groups.sort(key=lambda x: -len(x[1]))
                
                # Create a list of exam segments for bin-packing
                exam_segments = []
                for exam, students in exam_groups:
                    exam_segments.append(ExamSegment(exam, students))
                
                # Allocate using bin-packing approach
                allocated_segments = bin_pack_allocation(exam_segments, rooms, date, slot_name)
                
                # Update schedule and track assignments
                for room_id, segments in allocated_segments.items():
                    schedule[date][slot_name][room_id] = segments
                    for segment in segments:
                        # Update database with room assignments
                        StudentExam.objects.filter(
                            id__in=[se.id for se in segment.students]
                        ).update(room_id=room_id)
                
                # Track unaccommodated students
                all_allocated_students = set()
                for segments in allocated_segments.values():
                    for segment in segments:
                        all_allocated_students.update(se.id for se in segment.students)
                
                all_students = set()
                for exam, students in exam_groups:
                    all_students.update(se.id for se in students)
                
                unaccommodated_ids = all_students - all_allocated_students
                if unaccommodated_ids:
                    unaccommodated_students = StudentExam.objects.filter(id__in=unaccommodated_ids)
                    unaccommodated.extend([se.student for se in unaccommodated_students])

        logger.info(f"Allocation completed. {len(unaccommodated)} students unaccommodated.")
        return unaccommodated


class ExamSegment:
    """Represents a segment of an exam that can be allocated to a room."""
    
    def __init__(self, exam, students, segment_id=1):
        self.exam = exam
        self.students = students
        self.size = len(students)
        self.segment_id = segment_id
        self.semester = self._get_semester_number()
    
    def _get_semester_number(self):
        """Extract semester number for compatibility checking."""
        try:
            return int(self.exam.group.course.semester.name.split()[1])
        except (ValueError, IndexError, AttributeError):
            return 0
    
    def is_compatible(self, other_segment):
        """Check if two exam segments are compatible for room sharing."""
        if not other_segment:
            return True
        
        # Same exam cannot share room with itself
        if self.exam.id == other_segment.exam.id:
            return False
        
        # Prefer non-adjacent semesters (difference > 1)
        semester_diff = abs(self.semester - other_segment.semester)
        return semester_diff > 1
    
    def split(self, size1, size2):
        """Split exam segment into two parts."""
        if size1 + size2 != self.size:
            raise ValueError("Split sizes must sum to original size")
        
        students1 = self.students[:size1]
        students2 = self.students[size1:size1 + size2]
        
        segment1 = ExamSegment(self.exam, students1, 1)
        segment2 = ExamSegment(self.exam, students2, 2)
        
        return segment1, segment2


def bin_pack_allocation(exam_segments, rooms, date, slot_name):
    """
    Bin-packing algorithm for room allocation.
    Returns: {room_id: [ExamSegment]}
    """
    allocated_rooms = {}
    remaining_segments = exam_segments.copy()
    
    # Step 3: For each room, attempt to fit two courses
    for room in rooms:
        if not remaining_segments:
            break
            
        room_capacity = room.capacity
        best_allocation = find_best_room_allocation(remaining_segments, room_capacity)
        
        if best_allocation:
            allocated_rooms[room.id] = best_allocation['segments']
            # Remove allocated segments from remaining
            for segment in best_allocation['segments']:
                # Remove original segments or parts of them
                remaining_segments = update_remaining_segments(
                    remaining_segments, 
                    best_allocation['allocations']
                )
    
    # Step 4: Handle remaining segments (single course per room if needed)
    room_index = 0
    while remaining_segments and room_index < len(rooms):
        room = rooms[room_index]
        
        # Skip if room already allocated
        if room.id in allocated_rooms:
            room_index += 1
            continue
            
        # Find largest segment that fits
        for i, segment in enumerate(remaining_segments):
            if segment.size <= room.capacity:
                allocated_rooms[room.id] = [segment]
                remaining_segments.pop(i)
                break
        
        room_index += 1
    
    return allocated_rooms


def find_best_room_allocation(segments, room_capacity):
    """
    Find the best allocation for a single room using bin-packing logic.
    Prioritizes pairing compatible courses and maximizes space utilization.
    """
    best_allocation = None
    best_utilization = 0
    
    # Try all possible pairing combinations
    for i in range(len(segments)):
        segment1 = segments[i]
        
        # Try single segment allocation
        if segment1.size <= room_capacity:
            utilization = segment1.size / room_capacity
            if utilization > best_utilization:
                best_allocation = {
                    'segments': [segment1],
                    'utilization': utilization,
                    'allocations': [(i, segment1.size, None)]
                }
                best_utilization = utilization
        
        # Try pairing with other segments
        for j in range(i + 1, len(segments)):
            segment2 = segments[j]
            
            if not segment1.is_compatible(segment2):
                continue
            
            # Direct pairing
            if segment1.size + segment2.size <= room_capacity:
                utilization = (segment1.size + segment2.size) / room_capacity
                if utilization > best_utilization:
                    best_allocation = {
                        'segments': [segment1, segment2],
                        'utilization': utilization,
                        'allocations': [(i, segment1.size, None), (j, segment2.size, None)]
                    }
                    best_utilization = utilization
            
            # Try splitting larger segment to fit with smaller one
            larger_idx, smaller_idx = (i, j) if segment1.size >= segment2.size else (j, i)
            larger_seg = segments[larger_idx]
            smaller_seg = segments[smaller_idx]
            
            if smaller_seg.size < room_capacity:
                remaining_capacity = room_capacity - smaller_seg.size
                if remaining_capacity > 0 and remaining_capacity < larger_seg.size:
                    # Split larger segment
                    split_size = remaining_capacity
                    leftover_size = larger_seg.size - split_size
                    
                    utilization = room_capacity / room_capacity  # 100% utilization
                    if utilization > best_utilization:
                        try:
                            split1, split2 = larger_seg.split(split_size, leftover_size)
                            best_allocation = {
                                'segments': [split1, smaller_seg],
                                'utilization': utilization,
                                'allocations': [
                                    (larger_idx, split_size, leftover_size),
                                    (smaller_idx, smaller_seg.size, None)
                                ]
                            }
                            best_utilization = utilization
                        except ValueError:
                            continue
    
    return best_allocation


def update_remaining_segments(remaining_segments, allocations):
    """Update the remaining segments list based on allocations."""
    new_remaining = []
    
    for i, segment in enumerate(remaining_segments):
        allocated = False
        leftover_segment = None
        
        for alloc_idx, allocated_size, leftover_size in allocations:
            if i == alloc_idx:
                allocated = True
                if leftover_size and leftover_size > 0:
                    # Create leftover segment
                    leftover_students = segment.students[allocated_size:]
                    leftover_segment = ExamSegment(segment.exam, leftover_students)
                break
        
        if not allocated:
            new_remaining.append(segment)
        elif leftover_segment:
            new_remaining.append(leftover_segment)
    
    return new_remaining


# Performance monitoring and reporting
def generate_allocation_report(schedule):
    """Generate a detailed report of the allocation results."""
    total_rooms_used = 0
    total_capacity = 0
    total_students = 0
    shared_rooms = 0
    
    for date, slots in schedule.items():
        for slot_name, room_assignments in slots.items():
            for room_id, segments in room_assignments.items():
                total_rooms_used += 1
                room_capacity = Room.objects.get(id=room_id).capacity
                total_capacity += room_capacity
                
                room_students = sum(len(segment.students) for segment in segments)
                total_students += room_students
                
                if len(segments) > 1:
                    shared_rooms += 1
    
    utilization_rate = (total_students / total_capacity * 100) if total_capacity > 0 else 0
    sharing_rate = (shared_rooms / total_rooms_used * 100) if total_rooms_used > 0 else 0
    
    report = {
        'total_rooms_used': total_rooms_used,
        'total_capacity': total_capacity,
        'total_students_allocated': total_students,
        'utilization_rate': round(utilization_rate, 2),
        'shared_rooms': shared_rooms,
        'sharing_rate': round(sharing_rate, 2),
        'efficiency_score': round((utilization_rate + sharing_rate) / 2, 2)
    }
    
    logger.info(f"Allocation Report: {report}")
    return report
    
# from collections import defaultdict
# from django.db import transaction
# from datetime import time

# def allocate_shared_rooms():
#     """
#     Allocates exam rooms using bin-packing approach with smart pairing and group splitting
#     """
#     # Get all unassigned student exams with related data
#     student_exams = StudentExam.objects.filter(
#         room__isnull=True
#     ).select_related(
#         'exam',
#         'exam__group__course__semester',
#         'student'
#     ).order_by('exam__date', 'exam__start_time')
    
#     if not student_exams.exists():
#         return []

#     rooms = list(Room.objects.order_by('-capacity'))  # Largest rooms first
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     # Define time slots
#     SLOTS = [
#         ('Morning', time(8, 0), time(11, 0)),
#         ('Afternoon', time(13, 0), time(16, 0)),
#         ('Evening', time(18, 0), time(20, 0)),
#     ]

#     with transaction.atomic():
#         # Data structure: {date: {slot: [RoomAllocation]}}
#         schedule = defaultdict(lambda: defaultdict(list))
#         unaccommodated = []

#         # Organize students by date and slot
#         date_slot_students = defaultdict(lambda: defaultdict(list))
#         for se in student_exams:
#             for slot_name, start, end in SLOTS:
#                 if se.exam.start_time == start and se.exam.end_time == end:
#                     date_slot_students[se.exam.date][slot_name].append(se)
#                     break

#         # Process each date and slot using bin-packing
#         for date, slots in date_slot_students.items():
#             for slot_name, slot_start, slot_end in SLOTS:
#                 student_exams_slot = slots.get(slot_name, [])
#                 if not student_exams_slot:
#                     continue

#                 # Group by exam and sort by size (largest first)
#                 exam_groups = defaultdict(list)
#                 for se in student_exams_slot:
#                     exam_groups[se.exam].append(se)
                
#                 sorted_exam_groups = sorted(exam_groups.items(), key=lambda x: -len(x[1]))
                
#                 # Apply bin-packing allocation
#                 allocated_students = bin_pack_exams(sorted_exam_groups, rooms, date, slot_name)
                
#                 # Track unallocated students
#                 allocated_ids = {se.id for se in allocated_students}
#                 unallocated = [se for se in student_exams_slot if se.id not in allocated_ids]
#                 unaccommodated.extend([se.student for se in unallocated])
                
#                 # Store allocations in schedule for tracking
#                 room_allocations = defaultdict(list)
#                 for se in allocated_students:
#                     if se.room:
#                         room_allocations[se.room.id].append(se)
#                 schedule[date][slot_name] = dict(room_allocations)

#         return unaccommodated


# def bin_pack_exams(exam_groups, rooms, date, slot_name):
#     """
#     Core bin-packing algorithm for exam allocation
#     """
#     allocated_students = []
#     available_rooms = [(room, room.capacity) for room in rooms]  # (room, remaining_capacity)
#     remaining_groups = list(exam_groups)  # [(exam, students)]
    
#     while remaining_groups and available_rooms:
#         # Try to find the best allocation for current state
#         best_allocation = find_best_allocation(remaining_groups, available_rooms)
        
#         if not best_allocation:
#             break
            
#         # Apply the best allocation found
#         room_idx, allocations = best_allocation
#         room, remaining_capacity = available_rooms[room_idx]
        
#         students_to_allocate = []
#         total_allocated = 0
        
#         for exam, count, group_idx in allocations:
#             exam_students = remaining_groups[group_idx][1][:count]
#             students_to_allocate.extend(exam_students)
#             total_allocated += count
            
#             # Update remaining group size
#             remaining_groups[group_idx] = (exam, remaining_groups[group_idx][1][count:])
        
#         # Assign room to students
#         for se in students_to_allocate:
#             se.room = room
#             se.save()
#         allocated_students.extend(students_to_allocate)
        
#         # Update room capacity
#         new_capacity = remaining_capacity - total_allocated
#         if new_capacity > 0:
#             available_rooms[room_idx] = (room, new_capacity)
#         else:
#             available_rooms.pop(room_idx)
        
#         # Remove empty groups
#         remaining_groups = [(exam, students) for exam, students in remaining_groups if students]
    
#     return allocated_students


# def find_best_allocation(exam_groups, available_rooms):
#     """
#     Finds the best way to allocate exams to a room using bin-packing principles
#     """
#     best_allocation = None
#     best_score = 0
    
#     for room_idx, (room, capacity) in enumerate(available_rooms):
#         # Try different allocation strategies for this room
        
#         # Strategy 1: Try to pair two different semester groups
#         paired_allocation = try_pair_allocation(exam_groups, capacity)
#         if paired_allocation:
#             score = calculate_allocation_score(paired_allocation, capacity)
#             if score > best_score:
#                 best_score = score
#                 best_allocation = (room_idx, paired_allocation)
        
#         # Strategy 2: Try smart splitting of large groups
#         split_allocation = try_split_allocation(exam_groups, capacity)
#         if split_allocation:
#             score = calculate_allocation_score(split_allocation, capacity)
#             if score > best_score:
#                 best_score = score
#                 best_allocation = (room_idx, split_allocation)
        
#         # Strategy 3: Single group allocation (fallback)
#         single_allocation = try_single_allocation(exam_groups, capacity)
#         if single_allocation:
#             score = calculate_allocation_score(single_allocation, capacity)
#             if score > best_score:
#                 best_score = score
#                 best_allocation = (room_idx, single_allocation)
    
#     return best_allocation


# def try_pair_allocation(exam_groups, capacity):
#     """
#     Attempts to pair two exams from non-adjacent semesters
#     """
#     for i, (exam1, students1) in enumerate(exam_groups):
#         if not students1:
#             continue
            
#         sem1 = get_semester_number(exam1)
        
#         for j, (exam2, students2) in enumerate(exam_groups):
#             if i >= j or not students2:
#                 continue
                
#             sem2 = get_semester_number(exam2)
            
#             # Check if semesters are non-adjacent (difference > 1)
#             if abs(sem1 - sem2) > 1:
#                 # Calculate optimal split
#                 total_students = len(students1) + len(students2)
#                 if total_students <= capacity:
#                     # Both groups can fit entirely
#                     return [(exam1, len(students1), i), (exam2, len(students2), j)]
#                 else:
#                     # Try proportional splitting
#                     ratio1 = len(students1) / total_students
#                     count1 = min(len(students1), int(capacity * ratio1))
#                     count2 = min(len(students2), capacity - count1)
                    
#                     if count1 > 0 and count2 > 0:
#                         return [(exam1, count1, i), (exam2, count2, j)]
    
#     return None


# def try_split_allocation(exam_groups, capacity):
#     """
#     Attempts to split large groups optimally with smaller groups
#     """
#     for i, (large_exam, large_students) in enumerate(exam_groups):
#         if len(large_students) < capacity * 0.7:  # Only consider "large" groups
#             continue
            
#         large_sem = get_semester_number(large_exam)
        
#         # Look for a smaller group that could pair well
#         for j, (small_exam, small_students) in enumerate(exam_groups):
#             if i == j or not small_students:
#                 continue
                
#             small_sem = get_semester_number(small_exam)
            
#             # Check semester separation
#             if abs(large_sem - small_sem) > 1:
#                 small_count = len(small_students)
#                 large_count = capacity - small_count
                
#                 if large_count > 0 and large_count < len(large_students):
#                     # This creates a beneficial split
#                     return [(large_exam, large_count, i), (small_exam, small_count, j)]
    
#     return None


# def try_single_allocation(exam_groups, capacity):
#     """
#     Fallback: allocate single exam group to room
#     """
#     for i, (exam, students) in enumerate(exam_groups):
#         if students:
#             count = min(len(students), capacity)
#             return [(exam, count, i)]
    
#     return None


# def calculate_allocation_score(allocation, capacity):
#     """
#     Calculates score for an allocation (higher is better)
#     """
#     total_students = sum(count for _, count, _ in allocation)
#     utilization = total_students / capacity
    
#     # Prefer high utilization
#     score = utilization * 100
    
#     # Bonus for pairing (multiple exams in same room)
#     if len(allocation) > 1:
#         score += 20
    
#     # Bonus for full utilization
#     if utilization == 1.0:
#         score += 10
    
#     return score


# def get_semester_number(exam):
#     """
#     Extracts semester number from exam
#     """
#     try:
#         return int(exam.group.course.semester.name.split()[1])
#     except (ValueError, IndexError, AttributeError):
#         return 0


# from collections import defaultdict
# from django.db import transaction
# from datetime import time


# from collections import defaultdict
# from datetime import time
# from django.db import transaction


# def allocate_shared_rooms():
#     """
#     Bin packing-based exam allocation algorithm that optimizes room utilization
#     while respecting semester constraints and time slots.
#     """
#     # Get all unassigned student exams with related data
#     student_exams = StudentExam.objects.filter(
#         room__isnull=True
#     ).select_related(
#         'exam',
#         'exam__group__course__semester',
#         'student'
#     ).order_by('exam__date', 'exam__start_time')
    
#     if not student_exams.exists():
#         return []

#     # Sort rooms by capacity (descending - largest first)
#     rooms = list(Room.objects.order_by('-capacity'))
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     # Define time slots
#     SLOTS = [
#         ('Morning', time(8, 0), time(11, 0)),
#         ('Afternoon', time(13, 0), time(16, 0)),
#         ('Evening', time(18, 0), time(20, 0)),
#     ]

#     with transaction.atomic():
#         # Data structures for tracking allocations
#         # {date: {slot: {room_id: {'capacity': int, 'allocations': [{'exam': exam, 'students': [se], 'count': int}]}}}}
#         schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'capacity': 0, 'allocations': []})))
#         unaccommodated = []

#         # Initialize room capacities in schedule
#         for date_slots in schedule.values():
#             for slot_rooms in date_slots.values():
#                 for room in rooms:
#                     slot_rooms[room.id]['capacity'] = room.capacity

#         # Group students by date, slot, and exam
#         date_slot_exams = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        
#         for se in student_exams:
#             exam_date = se.exam.date
#             exam_start = se.exam.start_time
#             exam_end = se.exam.end_time
            
#             # Find matching slot
#             for slot_name, start, end in SLOTS:
#                 if exam_start == start and exam_end == end:
#                     date_slot_exams[exam_date][slot_name][se.exam].append(se)
#                     break

#         # Process each date and slot
#         for date, slots in date_slot_exams.items():
#             for slot_name, exams in slots.items():
                
#                 # Create exam items for bin packing (sorted by student count - descending)
#                 exam_items = []
#                 for exam, student_list in exams.items():
#                     semester_num = int(exam.group.course.semester.name.split()[1])
#                     exam_items.append({
#                         'exam': exam,
#                         'students': student_list,
#                         'count': len(student_list),
#                         'semester': semester_num
#                     })
                
#                 # Sort exams by student count (descending - largest first)
#                 exam_items.sort(key=lambda x: x['count'], reverse=True)
                
#                 # Bin packing allocation
#                 allocated_exams = set()
                
#                 for room in rooms:  # Already sorted by capacity (descending)
#                     if not exam_items:
#                         break
                        
#                     room_capacity = room.capacity
#                     room_allocations = []
#                     remaining_capacity = room_capacity
                    
#                     # Try to find the best combination for this room
#                     best_allocation = find_best_room_allocation(
#                         exam_items, remaining_capacity, allocated_exams
#                     )
                    
#                     if best_allocation:
#                         for exam_item in best_allocation:
#                             allocated_exams.add(exam_item['exam'].id)
#                             room_allocations.append(exam_item)
#                             remaining_capacity -= exam_item['count']
                        
#                         # Store the allocation
#                         schedule[date][slot_name][room.id]['allocations'] = room_allocations
#                         schedule[date][slot_name][room.id]['capacity'] = remaining_capacity
                
#                 # Collect unaccommodated students
#                 for exam_item in exam_items:
#                     if exam_item['exam'].id not in allocated_exams:
#                         unaccommodated.extend([se.student for se in exam_item['students']])

#         # Save all assignments to database
#         for date, slots in schedule.items():
#             for slot_name, room_assignments in slots.items():
#                 for room_id, room_data in room_assignments.items():
#                     for allocation in room_data['allocations']:
#                         StudentExam.objects.filter(
#                             id__in=[se.id for se in allocation['students']]
#                         ).update(room_id=room_id)

#         # Final attempt to place remaining students using any available space
#         if unaccommodated:
#             final_unaccommodated = final_placement_attempt(schedule, unaccommodated, rooms, SLOTS)
#             return final_unaccommodated

#     return unaccommodated


# def find_best_room_allocation(exam_items, room_capacity, allocated_exams):
#     """
#     Find the best combination of exams for a single room using bin packing principles.
#     Prioritizes semester separation and optimal space utilization.
#     """
#     available_exams = [item for item in exam_items if item['exam'].id not in allocated_exams]
    
#     if not available_exams:
#         return []
    
#     # Strategy 1: Try to pair exams from non-adjacent semesters
#     best_pair = find_semester_separated_pair(available_exams, room_capacity)
#     if best_pair:
#         return best_pair
    
#     # Strategy 2: Try half-half allocation for any two exams
#     best_half_half = find_half_half_allocation(available_exams, room_capacity)
#     if best_half_half:
#         return best_half_half
    
#     # Strategy 3: Single exam allocation (maximize utilization)
#     best_single = find_best_single_allocation(available_exams, room_capacity)
#     if best_single:
#         return [best_single]
    
#     return []


# def find_semester_separated_pair(exam_items, room_capacity):
#     """
#     Find the best pair of exams from non-adjacent semesters.
#     """
#     best_pair = None
#     best_utilization = 0
    
#     for i in range(len(exam_items)):
#         for j in range(i + 1, len(exam_items)):
#             exam1, exam2 = exam_items[i], exam_items[j]
            
#             # Check semester separation (non-adjacent)
#             if abs(exam1['semester'] - exam2['semester']) > 1:
#                 total_students = exam1['count'] + exam2['count']
                
#                 if total_students <= room_capacity:
#                     utilization = total_students / room_capacity
#                     if utilization > best_utilization:
#                         best_utilization = utilization
#                         best_pair = [exam1, exam2]
    
#     return best_pair


# def find_half_half_allocation(exam_items, room_capacity):
#     """
#     Find the best half-half allocation between two exams.
#     """
#     best_pair = None
#     best_utilization = 0
#     half_capacity = room_capacity // 2
    
#     for i in range(len(exam_items)):
#         for j in range(i + 1, len(exam_items)):
#             exam1, exam2 = exam_items[i], exam_items[j]
            
#             # Calculate how many students from each exam can fit in half the room
#             exam1_allocation = min(exam1['count'], half_capacity)
#             exam2_allocation = min(exam2['count'], half_capacity)
            
#             total_allocation = exam1_allocation + exam2_allocation
            
#             if total_allocation > 0:
#                 utilization = total_allocation / room_capacity
                
#                 # Prefer allocations that are closer to equal halves
#                 balance_score = 1 - abs(exam1_allocation - exam2_allocation) / max(exam1_allocation, exam2_allocation, 1)
#                 combined_score = utilization * balance_score
                
#                 if combined_score > best_utilization:
#                     best_utilization = combined_score
                    
#                     # Create modified exam items with limited student counts
#                     modified_exam1 = exam1.copy()
#                     modified_exam1['students'] = exam1['students'][:exam1_allocation]
#                     modified_exam1['count'] = exam1_allocation
                    
#                     modified_exam2 = exam2.copy()
#                     modified_exam2['students'] = exam2['students'][:exam2_allocation]
#                     modified_exam2['count'] = exam2_allocation
                    
#                     best_pair = [modified_exam1, modified_exam2]
    
#     return best_pair


# def find_best_single_allocation(exam_items, room_capacity):
#     """
#     Find the best single exam allocation that maximizes room utilization.
#     """
#     best_exam = None
#     best_utilization = 0
    
#     for exam_item in exam_items:
#         students_to_allocate = min(exam_item['count'], room_capacity)
        
#         if students_to_allocate > 0:
#             utilization = students_to_allocate / room_capacity
            
#             if utilization > best_utilization:
#                 best_utilization = utilization
                
#                 # Create modified exam item if needed
#                 if students_to_allocate < exam_item['count']:
#                     modified_exam = exam_item.copy()
#                     modified_exam['students'] = exam_item['students'][:students_to_allocate]
#                     modified_exam['count'] = students_to_allocate
#                     best_exam = modified_exam
#                 else:
#                     best_exam = exam_item
    
#     return best_exam


# def final_placement_attempt(schedule, unaccommodated_students, rooms, SLOTS):
#     """
#     Final attempt to place remaining students in any available space.
#     """
#     remaining_students = unaccommodated_students.copy()
    
#     # Get remaining student exams
#     remaining_exams = StudentExam.objects.filter(
#         student__in=remaining_students,
#         room__isnull=True
#     ).select_related('exam')

#     for se in remaining_exams:
#         date = se.exam.date
#         exam_start = se.exam.start_time
#         exam_end = se.exam.end_time
        
#         # Find the slot
#         for slot_name, start, end in SLOTS:
#             if exam_start == start and exam_end == end:
                
#                 # Try to find any room with remaining capacity
#                 for room in rooms:
#                     current_capacity = schedule[date][slot_name][room.id]['capacity']
                    
#                     if current_capacity > 0:
#                         # Assign this student
#                         se.room = room
#                         se.save()
                        
#                         # Update schedule
#                         schedule[date][slot_name][room.id]['capacity'] -= 1
                        
#                         # Remove from unaccommodated list
#                         try:
#                             remaining_students.remove(se.student)
#                         except ValueError:
#                             pass
                        
#                         break
#                 break
    
#     return remaining_students

# def allocate_shared_rooms():
#     # Get all unassigned student exams with related data
#     student_exams = StudentExam.objects.filter(
#         room__isnull=True
#     ).select_related(
#         'exam',
#         'exam__group__course__semester',
#         'student'
#     ).order_by('exam__date', 'exam__start_time')
    
#     if not student_exams.exists():
#         return []

#     rooms = list(Room.objects.order_by('-capacity'))
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     # Define time slots
#     SLOTS = [
#         ('Morning', time(8, 0), time(11, 0)),
#         ('Afternoon', time(13, 0), time(16, 0)),
#         ('Evening', time(18, 0), time(20, 0)),
#     ]

#     with transaction.atomic():
#         # Data structure: {date: {slot: {room: [student_exams]}}}
#         schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
#         unaccommodated = []

#         # Organize students by date and slot
#         date_slot_students = defaultdict(lambda: defaultdict(list))
#         for se in student_exams:
#             for slot_name, start, end in SLOTS:
#                 if se.exam.start_time == start and se.exam.end_time == end:
#                     date_slot_students[se.exam.date][slot_name].append(se)
#                     break

#         # Process each date and slot
#         for date, slots in date_slot_students.items():
#             for slot_name, slot_start, slot_end in SLOTS:
#                 student_exams = slots.get(slot_name, [])
#                 if not student_exams:
#                     continue

#                 # Group by exam
#                 exams = defaultdict(list)
#                 for se in student_exams:
#                     exams[se.exam].append(se)

#                 # Sort exams by student count (descending)
#                 sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))

#                 # Assign to rooms
#                 room_index = 0
#                 remaining_students = student_exams.copy()

#                 while remaining_students and room_index < len(rooms):
#                     room = rooms[room_index]
#                     room_index += 1

#                     # Check if room is already used in this slot
#                     if room.id in schedule[date][slot_name]:
#                         continue

#                     # Calculate available capacity
#                     current_usage = len(schedule[date][slot_name].get(room.id, []))
#                     available = room.capacity - current_usage

#                     if available <= 0:
#                         continue

#                     # Try to find compatible exams to pair
#                     best_pair = None
#                     best_pair_size = 0

#                     # Look for two exams that can share the room
#                     for i in range(len(sorted_exams)):
#                         exam1, students1 = sorted_exams[i]
#                         if not students1:
#                             continue
                        
#                         for j in range(i+1, len(sorted_exams)):
#                             exam2, students2 = sorted_exams[j]
#                             if not students2:
#                                 continue
                            
#                             # Check semester separation
#                             sem1 = int(exam1.group.course.semester.name.split()[1])
#                             sem2 = int(exam2.group.course.semester.name.split()[1])
#                             if abs(sem1 - sem2) > 1:
#                                 pair_size = min(len(students1), len(students2), available//2)
#                                 if pair_size > best_pair_size:
#                                     best_pair = (exam1, exam2, pair_size)
#                                     best_pair_size = pair_size

#                     if best_pair:
#                         exam1, exam2, pair_size = best_pair
#                         # Assign students from both exams
#                         assigned = []
#                         for exam in [exam1, exam2]:
#                             exam_students = [se for se in remaining_students if se.exam == exam]
#                             to_assign = exam_students[:pair_size]
#                             assigned.extend(to_assign)
#                             for se in to_assign:
#                                 remaining_students.remove(se)
#                         schedule[date][slot_name][room.id].extend(assigned)
#                     else:
#                         # Assign single exam to room
#                         exam, students = next(((e, s) for e, s in sorted_exams if s), (None, None))
#                         if exam:
#                             exam_students = [se for se in remaining_students if se.exam == exam]
#                             to_assign = exam_students[:available]
#                             schedule[date][slot_name][room.id].extend(to_assign)
#                             for se in to_assign:
#                                 remaining_students.remove(se)

#                 # Track unassigned students
#                 unaccommodated.extend([se.student for se in remaining_students])

#         # Save all assignments to database
#         for date, slots in schedule.items():
#             for slot_name, room_assignments in slots.items():
#                 for room_id, student_exams in room_assignments.items():
#                     StudentExam.objects.filter(
#                         id__in=[se.id for se in student_exams]
#                     ).update(room_id=room_id)

#         # Final attempt to place remaining students
#         if unaccommodated:
#             remaining_exams = StudentExam.objects.filter(
#                 student__in=unaccommodated,
#                 room__isnull=True
#             ).select_related('exam')

#             for se in remaining_exams:
#                 date = se.exam.date
#                 for slot_name, start, end in SLOTS:
#                     if se.exam.start_time == start and se.exam.end_time == end:
#                         # Find any room with space in this slot
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
# from django.db import transaction


# def allocate_shared_rooms(exams_by_date):
#     """
#     exams_by_date: dict mapping date -> list of StudentExam instances for that date
#     returns: list of Student instances who couldn't be placed
#     """from collections import Counter, defaultdict
# from datetime import time
# from django.db import transaction
# from collections import defaultdict
# from datetime import time
# from django.db import transaction

# def allocate_shared_rooms():
#     exams_qs = StudentExam.objects.filter(
#         room__isnull=True
#     ).select_related(
#         'exam__group__course__semester',
#         'student'
#     ).order_by('exam__date', 'exam__start_time')
#     if not exams_qs.exists():
#         return []

#     rooms = list(Room.objects.order_by('-capacity'))
#     SLOTS = [
#         ('Morning', time(8,0), time(11,0)),
#         ('Afternoon', time(13,0), time(16,0)),
#         ('Evening', time(18,0), time(20,0)),
#     ]

#     with transaction.atomic():
#         unaccommodated = []
#         assignments   = []

#         # Bucket by date & slot
#         by_date_slot = defaultdict(lambda: defaultdict(list))
#         for se in exams_qs:
#             for slot_name, start, end in SLOTS:
#                 if se.exam.start_time == start and se.exam.end_time == end:
#                     by_date_slot[se.exam.date][slot_name].append(se)
#                     break

#         for date, slots in by_date_slot.items():
#             for slot_name, _, _ in SLOTS:
#                 bucket = slots.get(slot_name, [])
#                 if not bucket:
#                     continue

#                 # Build per‐exam lists
#                 exam_map = defaultdict(list)
#                 for se in bucket:
#                     exam_map[se.exam].append(se)
#                 counts = {e: list(lst) for e, lst in exam_map.items()}

#                 # DEBUG #1: Slot start
#                 total = sum(len(lst) for lst in counts.values())
#                 print(f"--- SLOT START {date} {slot_name}: total_students = {total}")

#                 # Fill rooms
#                 for room in rooms:
#                     cap = room.capacity
#                     if not any(counts.values()):
#                         break

#                     # Primary fill
#                     primary = max(counts, key=lambda e: len(counts[e]))
#                     take_p = min(len(counts[primary]), cap)
#                     batch_p = counts[primary][:take_p]
#                     counts[primary] = counts[primary][take_p:]
#                     cap -= take_p

#                     # Secondary fill (semester ±1)
#                     batch_s = []
#                     if cap > 0:
#                         sem1 = int(primary.group.course.semester.name.split()[1])
#                         cands = [
#                             e for e, lst in counts.items()
#                             if lst and abs(int(e.group.course.semester.name.split()[1]) - sem1) == 1
#                         ]
#                         if cands:
#                             sec = max(cands, key=lambda e: len(counts[e]))
#                             take_s = min(len(counts[sec]), cap)
#                             batch_s = counts[sec][:take_s]
#                             counts[sec] = counts[sec][take_s:]
#                             cap -= take_s

#                     # Commit
#                     for se in batch_p + batch_s:
#                         assignments.append((se.id, room.id))

#                     # DEBUG #2: After each room
#                     placed = len(batch_p) + len(batch_s)
#                     cumul = total - sum(len(lst) for lst in counts.values())
#                     print(f" Room {room.id}: placed {placed}, cumul_assigned = {cumul}, room_cap={room.capacity}")

#                 # Anything left is unaccommodated
#                 leftovers = sum(len(lst) for lst in counts.values())
#                 for lst in counts.values():
#                     unaccommodated.extend(lst)

#                 # DEBUG #3: Slot end
#                 print(f"--- SLOT END   {date} {slot_name}: unassigned = {leftovers}")

#         # Persist assignments
#         for se_id, room_id in assignments:
#             StudentExam.objects.filter(id=se_id).update(room_id=room_id)

#         return [se.student_id for se in unaccommodated]

#     if not exams_by_date:
#         return []

#     all_rooms = list(Room.objects.order_by('-capacity'))
#     if not all_rooms:
#         raise Exception("No rooms available for allocation.")

#     SLOTS = [
#         ('morning', time(8, 0), time(11, 0)),
#         ('afternoon', time(13, 0), time(16, 0)),
#         ('evening', time(18, 0), time(20, 0)),
#     ]

#     unaccommodated = []

#     with transaction.atomic():
#         for date, student_exams in exams_by_date.items():
#             # bucket by slot
#             slots = defaultdict(list)
#             for se in student_exams:
#                 for name, start, end in SLOTS:
#                     if se.exam.start_time == start and se.exam.end_time == end:
#                         slots[name].append(se)
#                         break

#             for slot_name, ses in slots.items():
#                 # copy fresh rooms for this slot
#                 rooms = all_rooms.copy()
#                 # map exam_id -> deque of StudentExam
#                 exam_queues = defaultdict(list)
#                 for se in ses:
#                     exam_queues[se.exam.id].append(se)
#                 placed = set()

#                 # helper to pop next two compatible exam_ids
#                 def pick_pair():
#                     ids = list(exam_queues.keys())
#                     for i in range(len(ids)):
#                         for j in range(i+1, len(ids)):
#                             # check non-adjacent semesters
#                             e1, e2 = ids[i], ids[j]
#                             sem1 = int(Exam.objects.get(id=e1).group.course.semester.name.split()[1])
#                             sem2 = int(Exam.objects.get(id=e2).group.course.semester.name.split()[1])
#                             if abs(sem1 - sem2) > 1:
#                                 return e1, e2
#                     # no compatible: return single exam
#                     return (ids[0], None) if ids else (None, None)

#                 # allocate rooms
#                 while rooms and exam_queues:
#                     room = rooms.pop(0)
#                     e1, e2 = pick_pair()
#                     if not e1:
#                         break

#                     # decide split
#                     if e2:
#                         # two exams share
#                         cap1 = cap2 = room.capacity // 2
#                     else:
#                         cap1 = room.capacity
#                         cap2 = 0

#                     # allocate for exam 1
#                     q1 = exam_queues[e1]
#                     to_place1 = q1[:cap1]
#                     if to_place1:
#                         StudentExam.objects.filter(
#                             student_id__in=[se.student.id for se in to_place1],
#                             exam_id=e1
#                         ).update(room=room)
#                         placed.update([se.student.id for se in to_place1])
#                     exam_queues[e1] = q1[len(to_place1):]
#                     if not exam_queues[e1]:
#                         del exam_queues[e1]

#                     # allocate for exam 2 if any
#                     if e2:
#                         q2 = exam_queues[e2]
#                         to_place2 = q2[:cap2]
#                         if to_place2:
#                             StudentExam.objects.filter(
#                                 student_id__in=[se.student.id for se in to_place2],
#                                 exam_id=e2
#                             ).update(room=room)
#                             placed.update([se.student.id for se in to_place2])
#                         exam_queues[e2] = q2[len(to_place2):]
#                         if not exam_queues[e2]:
#                             del exam_queues[e2]

#                 # any leftover here are unaccommodated in this slot
#                 for remaining in exam_queues.values():
#                     unaccommodated.extend([se.student for se in remaining])

#         return unaccommodated

 
# def allocate_shared_rooms(exams):
#     if not exams:
#         return []

#     rooms = list(Room.objects.order_by('-capacity'))
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     unaccommodated_students = []
#     SLOTS = [
#         ('Morning', time(8, 0), time(11, 0)),
#         ('Afternoon', time(13, 0), time(16, 0)),
#         ('Evening', time(18, 0), time(20, 0)),
#     ]

#     with transaction.atomic():
#         for date, student_exams in exams.items():
#             # Group exams by time slot
#             time_slots = {
#                 'morning': [],
#                 'afternoon': [],
#                 'evening': []
#             }
            
#             for se in student_exams:
#                 if se.exam.start_time == SLOTS[0][1] and se.exam.end_time == SLOTS[0][2]:
#                     time_slots['morning'].append(se)
#                 elif se.exam.start_time == SLOTS[1][1] and se.exam.end_time == SLOTS[1][2]:
#                     time_slots['afternoon'].append(se)
#                 elif se.exam.start_time == SLOTS[2][1] and se.exam.end_time == SLOTS[2][2]:
#                     time_slots['evening'].append(se)

#             # Process each time slot
#             for slot_name in ['morning', 'afternoon', 'evening']:
#                 slot_exams = time_slots[slot_name]
#                 if not slot_exams:
#                     continue

#                 # Track which students have been assigned rooms
#                 assigned_students = set()
#                 room_index = 0

#                 # Step 1: Create exam pairs avoiding adjacent semesters
#                 exam_pairs = []
#                 used_exams = set()

#                 for i in range(len(slot_exams)):
#                     if slot_exams[i].exam.id in used_exams:
#                         continue
#                     for j in range(i + 1, len(slot_exams)):
#                         if slot_exams[j].exam.id in used_exams:
#                             continue
#                         try:
#                             sem_i = int(slot_exams[i].exam.group.course.semester.name.split(" ")[1])
#                             sem_j = int(slot_exams[j].exam.group.course.semester.name.split(" ")[1])
#                             if abs(sem_i - sem_j) > 1:
#                                 exam_pairs.append((slot_exams[i], slot_exams[j]))
#                                 used_exams.update({slot_exams[i].exam.id, slot_exams[j].exam.id})
#                                 break
#                         except (AttributeError, IndexError, ValueError):
#                             continue
#                     else:
#                         exam_pairs.append((slot_exams[i], None))
#                         used_exams.add(slot_exams[i].exam.id)

#                 # Step 2: Allocate rooms to exam pairs
#                 for pair in exam_pairs:
#                     if room_index >= len(rooms):
#                         # No rooms left, mark all as unaccommodated
#                         unaccommodated_students.extend([se.student for se in slot_exams if se.student.id not in assigned_students])
#                         continue

#                     room = rooms[room_index]
#                     room_index += 1
#                     capacity_per_exam = room.capacity // 2

#                     exams_to_allocate = [pair[0]]
#                     if pair[1]:
#                         exams_to_allocate.append(pair[1])

#                     for exam_se in exams_to_allocate:
#                         exam_students = [se for se in slot_exams 
#                                        if se.exam.id == exam_se.exam.id 
#                                        and se.student.id not in assigned_students]
#                         allocated = exam_students[:capacity_per_exam]
#                         overflow = exam_students[capacity_per_exam:]

#                         # Update existing StudentExam records
#                         student_ids = [se.student.id for se in allocated]
#                         StudentExam.objects.filter(
#                             student_id__in=student_ids,
#                             exam_id=exam_se.exam.id
#                         ).update(room=room)
#                         assigned_students.update(student_ids)

#                         if overflow:
#                             # These will be handled in the overflow phase
#                             pass

#                 # Step 3: Handle overflow students (those not assigned in first pass)
#                 remaining_exams = defaultdict(list)
#                 for se in slot_exams:
#                     if se.student.id not in assigned_students:
#                         remaining_exams[se.exam.id].append(se)

#                 while room_index < len(rooms) and remaining_exams:
#                     room = rooms[room_index]
#                     room_index += 1
#                     capacity_per_exam = room.capacity // 2

#                     # Get all remaining exams with students
#                     exam_ids = list(remaining_exams.keys())
                    
#                     # Try to find two compatible exams
#                     paired = False
#                     for i in range(len(exam_ids)):
#                         for j in range(i+1, len(exam_ids)):
#                             exam1_id = exam_ids[i]
#                             exam2_id = exam_ids[j]
#                             try:
#                                 exam1 = Exam.objects.get(id=exam1_id)
#                                 exam2 = Exam.objects.get(id=exam2_id)
#                                 sem1 = int(exam1.group.course.semester.name.split(" ")[1])
#                                 sem2 = int(exam2.group.course.semester.name.split(" ")[1])
#                                 if abs(sem1 - sem2) > 1:
#                                     # Found compatible pair
#                                     exam1_students = remaining_exams[exam1_id][:capacity_per_exam]
#                                     exam2_students = remaining_exams[exam2_id][:capacity_per_exam]
                                    
#                                     # Assign students
#                                     student_ids = [se.student.id for se in exam1_students + exam2_students]
#                                     StudentExam.objects.filter(
#                                         student_id__in=student_ids,
#                                         exam_id__in=[exam1_id, exam2_id]
#                                     ).update(room=room)
#                                     assigned_students.update(student_ids)
                                    
#                                     # Remove assigned students
#                                     remaining_exams[exam1_id] = remaining_exams[exam1_id][capacity_per_exam:]
#                                     remaining_exams[exam2_id] = remaining_exams[exam2_id][capacity_per_exam:]
                                    
#                                     # Clean up empty exams
#                                     if not remaining_exams[exam1_id]:
#                                         del remaining_exams[exam1_id]
#                                     if not remaining_exams[exam2_id]:
#                                         del remaining_exams[exam2_id]
                                    
#                                     paired = True
#                                     break
#                             except:
#                                 continue
#                         if paired:
#                             break

#                     if not paired and exam_ids:
#                         # Assign single exam to room
#                         exam_id = exam_ids[0]
#                         students = remaining_exams[exam_id][:room.capacity]
                        
#                         student_ids = [se.student.id for se in students]
#                         StudentExam.objects.filter(
#                             student_id__in=student_ids,
#                             exam_id=exam_id
#                         ).update(room=room)
#                         assigned_students.update(student_ids)
                        
#                         remaining_exams[exam_id] = remaining_exams[exam_id][room.capacity:]
#                         if not remaining_exams[exam_id]:
#                             del remaining_exams[exam_id]

#                 # Step 4: Any remaining unaccommodated students
#                 for exam_id in remaining_exams:
#                     for student_exam in remaining_exams[exam_id]:
#                         unaccommodated_students.append(student_exam.student)

#         # Final pass to try placing unaccommodated students in any remaining seats
#         if unaccommodated_students:
#             remaining_rooms = Room.objects.exclude(
#                 id__in=StudentExam.objects.filter(
#                     exam__date=date
#                 ).values_list('room_id', flat=True).distinct()
#             ).order_by('-capacity')

#             for room in remaining_rooms:
#                 current_allocations = StudentExam.objects.filter(room=room, exam__date=date).count()
#                 available_seats = room.capacity - current_allocations
                
#                 if available_seats > 0 and unaccommodated_students:
#                     students_to_place = unaccommodated_students[:available_seats]
#                     unaccommodated_students = unaccommodated_students[available_seats:]
                    
#                     # Update existing records
#                     student_ids = [s.id for s in students_to_place]
#                     exam_ids = [se.exam.id for se in student_exams if se.student.id in student_ids]
                    
#                     StudentExam.objects.filter(
#                         student_id__in=student_ids,
#                         exam_id__in=exam_ids
#                     ).update(room=room)

#     return unaccommodated_students

 

# def allocate_shared_rooms(exams):
#     if not exams:
#         return []

#     rooms = list(Room.objects.order_by('-capacity'))
#     unaccommodated_students = []
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     for date, students_exams in exams.items():
#         morning_exams=[]
#         afernoon_exams=[]
#         evening_exams=[]
#         for e in students_exams:
#             if e.exam.start_time== SLOTS[0][1] and e.exam.end_time==SLOTS[0][2]:
#                 morning_exams.append(e)
#             elif e.exam.start_time== SLOTS[1][1] and e.exam.end_time==SLOTS[1][2]:
#                 afernoon_exams.append(e)
#             elif e.exam.start_time== SLOTS[2][1] and e.exam.end_time==SLOTS[2][2]:
#                 evening_exams.append(e)
        
#         while morning_exams: 

           

#             # Step 2: Prepare exam pairs - pair exams (avoid adjacent semester pairing if needed)
#             exam_pairs = []
#             used_exams = set()

#             for i in range(len(morning_exams)):
#                 if morning_exams[i].exam.id in used_exams:
#                     continue
#                 for j in range(i + 1, len(morning_exams)):
#                     if morning_exams[j].exam.id in used_exams:
#                         continue
#                     if abs(int(morning_exams[i].exam.group.course.semester.name.split(" ")[1]) - int(morning_exams[j].exam.group.course.semester.name.split(" ")[1])) > 1:
#                         exam_pairs.append((morning_exams[i], morning_exams[j]))
#                         used_exams.update({morning_exams[i].id, morning_exams[j].id})
#                         break
#                 else:
#                     # If no suitable pair, leave it as single
#                     exam_pairs.append((morning_exams[i], None))
#                     used_exams.add(morning_exams[i].exam.id)

#             room_index = 0
#             assigned_student_exams = []
#             students_by_exam={}

#             # Step 3: Allocate rooms per exam pair
#             for pair in exam_pairs:
#                 if room_index >= len(rooms):
#                     # No rooms left, all students unaccommodated
#                     if pair[0]:
#                         unaccommodated_students.extend([s.student for s in morning_exams])
#                     if pair[1]:
#                         unaccommodated_students.extend([s.student for s in morning_exams])
#                     continue

#                 room = rooms[room_index]
#                 room_index += 1

#                 capacity = room.capacity
#                 cap_per_exam = capacity // 2

#                 exams_to_allocate = [pair[0]]
#                 if pair[1]:
#                     exams_to_allocate.append(pair[1])

#                 for exam in exams_to_allocate:
#                     exam_students=[s for s in morning_exams if s.exam.id == exam.id]
#                     students =  exam_students
#                     allocated = students[:cap_per_exam]
#                     overflow = students[cap_per_exam:]

#                     for studentExam in allocated:
#                         assigned_student_exams.append(StudentExam(student=studentExam.student, exam=exam, room=room))

#                     students_by_exam[exam.id] = overflow  

#             # Step 4: Allocate overflow students into any remaining rooms (2 exams per room rule)
#             remaining_studentexams = [studentexam for studentexam in morning_exams if students_by_exam[exam.id]]

#             while room_index < len(rooms) and remaining_studentexams:
#                 room = rooms[room_index]
#                 room_index += 1
#                 cap_per_exam = room.capacity // 2

#                 # Try to pick two exams with remaining students
#                 first_studentexam = remaining_studentexams.pop(0)
#                 second_studentexam = None

#                 for i, exam_id in enumerate(remaining_studentexams):
#                     if abs(
#                         int(first_studentexam.exam.group.course.semester.name.split(" ")[1])-
#                         int(first_studentexam.exam.group.course.semester.name.split(" ")[1])
#                     ) >1:
#                         second_exam_id = exam_id
#                         remaining_studentexams.pop(i)
#                         break

#                 exams_in_room = [first_studentexam.exam.id] if not second_exam_id else [first_studentexam.exam.id, second_studentexam.id]

#                 for exam_id in exams_in_room:
#                     exam = Exam.objects.get(id=exam_id)
#                     students=[s for s in morning_exams if s.exam.id == exam_id]
#                     allocated = students[:cap_per_exam]
#                     overflow = students[cap_per_exam:]

#                     for studentexam in allocated:
#                         se=StudentExam.objects.filter(student=studentexam.student, exam=exam).first()
#                         se.room=room
#                         se.save()

#                     students_by_exam[exam_id] = overflow
#                     if overflow:
#                         remaining_studentexams.append(exam_id)  # Still has overflow

#             # Step 5: Any remaining unaccommodated students
#             for exam_id in students_by_exam:
#                 for enrollment in students_by_exam[exam_id]:
#                     unaccommodated_students.append(enrollment.student)
 
#     return None
 
 
 



 
 
def verify_day_off_constraints(min_gap_days=1):
    """
    Verify that the current schedule maintains day-off constraints
    """
    violations = []
    
    # Get all student exam dates
    student_exam_dates = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exam_dates[student_exam.student.id].append(student_exam.exam.date)
    
    # Check each student's schedule
    for student_id, exam_dates in student_exam_dates.items():
        if len(exam_dates) < 2:
            continue
            
        sorted_dates = sorted(exam_dates)
        for i in range(len(sorted_dates) - 1):
            gap = (sorted_dates[i + 1] - sorted_dates[i]).days
            if gap < min_gap_days:
                violations.append(f"Student {student_id}: {gap} day gap between {sorted_dates[i]} and {sorted_dates[i + 1]}")
    
    return violations

def are_semesters_compatible(exam1, exam2):
    # Returns True if semesters have a gap of at least 2
    return abs(int(exam1.course.semester.name.split(" ")[1]) - int(exam2.course.semester.name.split(" ")[1])) > 1

def allocate_single_exam_rooms(exam):
    """
    Allocate students to rooms for a single exam
    Returns a list of students who couldn't be accommodated
    """
    rooms = list(Room.objects.order_by('-capacity'))
    
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    student_exam_qs = StudentExam.objects.filter(exam=exam).select_related('student')
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
            
        chunk = unassigned[:room.capacity]
        for se in chunk:
            se.room = room
            se.save(update_fields=['room'])
            
        unassigned = unassigned[room.capacity:]
    
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
        weekday = new_date.strftime('%A')
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")
        
        # 2. VALIDATE AND SET TIME SLOT
        new_start_time = exam.start_time  # Default to current time
        new_end_time = exam.end_time
        
        if slot:
            # Friday slot validation
            if weekday == 'Friday':
                available_slots = FRIDAY_SLOTS
            else:
                available_slots = SLOTS
            
            slot_match = next((s for s in available_slots if s[0].lower() == slot.lower()), None)
            if not slot_match:
                available_slot_names = [s[0] for s in available_slots]
                raise ValueError(
                    f"Invalid slot '{slot}' for {weekday}. "
                    f"Available slots: {', '.join(available_slot_names)}"
                )
            
            _, new_start_time, new_end_time = slot_match
        else:
            # If no slot specified, validate current time slot is valid for the new day
            if weekday == 'Friday':
                # Check if current time slot is valid for Friday
                current_slot = (exam.start_time, exam.end_time)
                friday_times = [(start, end) for _, start, end in FRIDAY_SLOTS]
                
                if current_slot not in friday_times:
                    available_slots = [f"{label} ({start}-{end})" for label, start, end in FRIDAY_SLOTS]
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
                student=enrollment.student,
                exam__date=new_date
            ).exclude(exam_id=exam_id)
            
            if existing_exams.exists():
                conflicted_students.append({
                    'student': enrollment.student.reg_no,
                    'conflicting_exams': [se.exam.course.title for se in existing_exams]
                })
        
        if conflicted_students:
            conflict_details = []
            for conflict in conflicted_students[:3]:   
                courses = ', '.join(conflict['conflicting_exams'])
                conflict_details.append(f"{conflict['student']} (conflicts with: {courses})")
            
            error_msg = f"Student conflicts found: {'; '.join(conflict_details)}"
            if len(conflicted_students) > 3:
                error_msg += f" ... and {len(conflicted_students) - 3} more students"
            
            raise ValueError(error_msg)
        
        # 4. CHECK ROOM CAPACITY CONFLICTS
        # Get number of students for this exam
        exam_student_count = Enrollment.objects.filter(course=exam.course).count()
        
        # Check existing exams in the same time slot
        existing_slot_exams = Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ).exclude(id=exam_id)
        
        # Calculate total students that would need accommodation in this slot
        total_students_needed = exam_student_count
        other_exams_students = 0
        
        for other_exam in existing_slot_exams:
            other_exam_students = Enrollment.objects.filter(course=other_exam.course).count()
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
                Enrollment.objects.filter(course=exam.course)
                .values_list('student_id', flat=True)
            )
            
            for other_exam in existing_slot_exams:
                other_students = set(
                    Enrollment.objects.filter(course=other_exam.course)
                    .values_list('student_id', flat=True)
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
                student_count = Enrollment.objects.filter(course=slot_exam.course).count()
                room_requirements.append(student_count)
            
            # Check if we can fit all exams in available rooms
            rooms = list(Room.objects.order_by('-capacity'))
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
        slot_exams = list(Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ))
        
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
            
        weekday = current.strftime('%A')
        if weekday in NO_EXAM_DAYS:
            current += timedelta(days=1)
            continue
        
        # Get available slots for this day
        available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
        
        for slot_name, start_time, end_time in available_slots:
            try:
                # Test if this slot would work (without actually rescheduling)
                test_conflicts = check_reschedule_feasibility(exam_id, current, slot_name)
                if not test_conflicts:
                    suggestions.append({
                        'date': current,
                        'slot': slot_name,
                        'start_time': start_time,
                        'end_time': end_time,
                        'weekday': weekday
                    })
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
        weekday = new_date.strftime('%A')
        
        # Check day validity
        if weekday in NO_EXAM_DAYS:
            conflicts.append(f"Cannot schedule on {weekday}")
            return conflicts
        
        # Check slot validity
        available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
        slot_match = next((s for s in available_slots if s[0].lower() == slot_name.lower()), None)
        if not slot_match:
            conflicts.append(f"Invalid slot '{slot_name}' for {weekday}")
            return conflicts
        
        _, new_start_time, new_end_time = slot_match
        
        # Check student conflicts
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        student_conflicts = 0
        
        for enrollment in enrolled_students:
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student,
                exam__date=new_date
            ).exclude(exam_id=exam_id)
            
            if existing_exams.exists():
                student_conflicts += 1
        
        if student_conflicts > 0:
            conflicts.append(f"{student_conflicts} student conflicts")
        
        # Check room capacity
        exam_students = Enrollment.objects.filter(course=exam.course).count()
        existing_slot_exams = Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ).exclude(id=exam_id)
        
        total_students = exam_students
        for other_exam in existing_slot_exams:
            total_students += Enrollment.objects.filter(course=other_exam.course).count()
        
        total_capacity = get_total_room_capacity()
        if total_students > total_capacity:
            conflicts.append(f"Insufficient capacity ({total_students} needed, {total_capacity} available)")
        
    except Exception as e:
        conflicts.append(f"Error checking feasibility: {str(e)}")
    
    return conflicts

def get_unaccommodated_students():
    """
    Get a list of students who couldn't be accommodated in the exam schedule
    """
    # Students without a room assignment
    unaccommodated = StudentExam.objects.filter(room__isnull=True).select_related('student', 'exam__course')
    
    result = []
    for student_exam in unaccommodated:
        result.append({
            'student': student_exam.student,
            'course': student_exam.exam.course,
            'exam_date': student_exam.exam.date,
            'exam_slot': (student_exam.exam.start_time, student_exam.exam.end_time)
        })
    
    return result
 

def verify_exam_schedule():
    """
    Verify that the current exam schedule has no conflicts
    Returns a list of any conflicts found
    """
    conflicts = []
    
    # Check for students with multiple exams in one day
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exams[student_exam.student.id].append(student_exam)
    
    for student_id, exams in student_exams.items():
        exams_by_date = defaultdict(list)
        for exam in exams:
            exams_by_date[exam.exam.date].append(exam)
        
        for date, day_exams in exams_by_date.items():
            if len(day_exams) > 1:
                conflicts.append({
                    'type': 'multiple_exams_per_day',
                    'student_id': student_id,
                    'date': date,
                    'exams': [e.exam.id for e in day_exams]
                })
    
    # Check for room overallocation
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.all():
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)
    
    for slot, slot_exams in exams_by_slot.items():
        room_student_counts = defaultdict(lambda: defaultdict(int))
        
        for exam in slot_exams:
            student_exams = StudentExam.objects.filter(exam=exam).select_related('room')
            for se in student_exams:
                if se.room:
                    room_student_counts[se.room.id][exam.id] += 1
        
        for room_id, exam_counts in room_student_counts.items():
            room = Room.objects.get(id=room_id)
            total_students = sum(exam_counts.values())
            
            if total_students > room.capacity:
                conflicts.append({
                    'type': 'room_overallocation',
                    'room_id': room_id,
                    'capacity': room.capacity,
                    'allocated': total_students,
                    'slot': slot,
                    'exams': list(exam_counts.keys())
                })
    
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
            for exam2 in slot_exams[i+1:]:
                # Check if these exams share any students
                students1 = set(Enrollment.objects.filter(course=exam1.course).values_list('student_id', flat=True))
                students2 = set(Enrollment.objects.filter(course=exam2.course).values_list('student_id', flat=True))
                
                common_students = students1.intersection(students2)
                if common_students:
                    conflicts.append({
                        'type': 'student_exam_conflict',
                        'course1': exam1.course.id,
                        'course2': exam2.course.id,
                        'common_students': list(common_students),
                        'slot': slot
                    })
    
    return conflicts



 