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
from notifications.tasks import send_exam_data

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
    return (
        Room.objects.filter().aggregate(total_capacity=Sum("capacity"))[
            "total_capacity"
        ]
        or 0
    )


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
from collections import defaultdict
from datetime import timedelta
from django.db.models import Min, Max, Prefetch

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
    date_range = Exam.objects.aggregate(
        min_date=Min("date"), 
        max_date=Max("date")
    )
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
        Enrollment.objects.filter(group_id__in=new_group)
        .values_list("student_id", flat=True)
    )

    # Bulk fetch all exams and related data for the date range
    all_exams = (
        Exam.objects
        .filter(date__in=dates_to_check)
        .select_related('group', 'group__course')
        .prefetch_related(
            Prefetch(
                'studentexam_set',
                queryset=StudentExam.objects.select_related('student')
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
                    if exam.group:
                        exam_student_ids = {se.student_id for se in exam.studentexam_set.all()}
                        if student_id in exam_student_ids:
                            conflicts.append({
                                "student": student_id,
                                "group": exam.group.group_name,
                                "course": exam.group.course.title,
                                "date": check_date,
                                "slot": slot,
                            })
                            break

        return conflicts, len(slot_students)

    def evaluate_slot_optimized(check_date, slot, is_suggested=False):
        """Optimized slot evaluation"""
        conflicts, student_count = check_slot_conflicts_optimized(check_date, slot)
        total_students = len(enrolled_students_new_group) + student_count

        suggestion_type = "Suggested slot" if is_suggested else "Slot"
        
        if conflicts:
            all_conflicts[check_date].extend(conflicts)
            all_suggestions.append({
                "suggested": False,
                "date": check_date,
                "slot": slot,
                "reason": f"{suggestion_type} {check_date} {slot} is not available (conflicts)",
            })
            return False
            
        elif not check_rooms_availability_for_slots(total_students):
            room_msg = f"{check_date} {slot} slot lacks room capacity"
            all_conflicts[check_date].append(room_msg)
            all_suggestions.append({
                "suggested": False,
                "date": check_date,
                "slot": slot,
                "reason": f"{suggestion_type} {check_date} {slot} is not available (insufficient rooms)",
            })
            return False
            
        else:
            all_suggestions.append({
                "suggested": True,
                "date": check_date,
                "slot": slot,
                "reason": f"Slot {check_date} {slot} is available",
            })
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
from collections import defaultdict
from django.db import models

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


# Alternative approach for very large datasets
def verify_groups_compatibility(groups):
    """
    Alternative implementation optimized for very large datasets.
    Uses bulk operations and minimal memory footprint.
    """
    
    # Use raw SQL for maximum performance if needed
    from django.db import connection
    
    with connection.cursor() as cursor:
        placeholders = ','.join(['%s'] * len(groups))
        cursor.execute(f"""
            SELECT course_id, group_id, student_id 
            FROM enrollments_enrollment 
            WHERE group_id IN ({placeholders})
            ORDER BY student_id, course_id, group_id
        """, groups)
        
        enrollments = cursor.fetchall()
    
    # Process results with minimal memory usage
    course_group_students = defaultdict(lambda: defaultdict(set))
    for course_id, group_id, student_id in enrollments:
        course_group_students[course_id][group_id].add(student_id)
    
    # Rest of the logic remains the same as the optimized version
    student_to_groups = defaultdict(set)
    for course_id, groups_dict in course_group_students.items():
        for group_id, students in groups_dict.items():
            for student_id in students:
                student_to_groups[student_id].add((course_id, group_id))
    
    group_conflicts = []
    processed_pairs = set()
    
    for student_id, student_groups in student_to_groups.items():
        if len(student_groups) > 1:
            student_groups_list = list(student_groups)
            for i in range(len(student_groups_list)):
                for j in range(i + 1, len(student_groups_list)):
                    course1, group1 = student_groups_list[i]
                    course2, group2 = student_groups_list[j]
                    


                    pair = tuple(sorted([(course1, group1), (course2, group2)]))
                    
                    if pair not in processed_pairs:
                        processed_pairs.add(pair)
                        students1 = course_group_students[course1][group1]
                        students2 = course_group_students[course2][group2]
                        shared_students = students1 & students2
                        
                        if shared_students:
                            group_conflicts.append((group1, group2, shared_students))
    
    return group_conflicts
 
def find_compatible_groups(groups):
    if not groups:
        return []
    sample_g=CourseGroup.objects.filter(id=groups[0])
    location = Course.objects.filter(id=sample_g.course.id).first().department.location.id
    total_seats = Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))["total"] or 0
    max_students_per_timeslot = total_seats * 3
    enrollments= Enrollment.objects.filter(group_id__in= groups)
    compatibles={}
    count=0
    for g in groups:
        if len(compatibles.keys())<1:
            compatibles[count]=set()

        g_students = enrollments.filter(group_id= g)
        for ck, cg in compatibles.items():
            if len(g_students.intersection(cg))>0:
                compatibles[count]=g_students
            else:
                compatibles[ck]= compatibles[ck].union(g_students)
        count+=1
    compatible_groups=set()
    for k,v in compatibles.items():
        # translate students to groups
        groups=set()
        for enrollment in v:
            grp= enrollment.group
            groups.add(grp)
        compatible_groups.add(groups)
    return compatible_groups
            
    
            





def find_compatible_courses_within_group(courses):
    if not courses:
        return [], defaultdict(list)
    
    # Get location and total capacity
    location = Course.objects.filter(id=courses[0]).first().department.location.id
    total_seats = Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))["total"] or 0
    max_students_per_timeslot = total_seats * 3
    
    # Get all enrollments and organize data
    course_students = defaultdict(set)
    course_group_details = defaultdict(lambda: defaultdict(list))
    course_group_students = defaultdict(lambda: defaultdict(set))
    course_group_sizes = defaultdict(lambda: defaultdict(int))
    
    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_students[enrollment.course_id].add(enrollment.student_id)
        course_group_details[enrollment.course_id][enrollment.group_id].append(enrollment.student_id)
        course_group_students[enrollment.course_id][enrollment.group_id].add(enrollment.student_id)
        course_group_sizes[enrollment.course_id][enrollment.group_id] += 1
    
    # Find course conflicts (students taking multiple courses)
    course_conflicts = defaultdict(list)
    for course1, course2 in combinations(course_students.keys(), 2):
        students1 = course_students[course1]
        students2 = course_students[course2]
        
        if students1 & students2:
            course_conflicts[course1].append(course2)
            course_conflicts[course2].append(course1)
    
    # Key fix: Build comprehensive group conflict map
    all_group_pairs = []
    for course_id in course_group_students:
        for group_id in course_group_students[course_id]:
            all_group_pairs.append((course_id, group_id))
    
    # Check every pair of groups for student conflicts
    group_conflicts = defaultdict(set)
    for i, (course1, group1) in enumerate(all_group_pairs):
        for j, (course2, group2) in enumerate(all_group_pairs[i+1:], i+1):
            students1 = course_group_students[course1][group1]
            students2 = course_group_students[course2][group2]
            
            # If groups share students, they cannot be in same timeslot
            if students1 & students2:
                group_conflicts[(course1, group1)].add((course2, group2))
                group_conflicts[(course2, group2)].add((course1, group1))
    
    # Enhanced scheduling algorithm with proper conflict checking
    timeslot_assignments = defaultdict(lambda: defaultdict(list))  # timeslot -> course -> groups
    timeslot_students = defaultdict(set)  # timeslot -> all student IDs
    timeslot_student_counts = defaultdict(int)  # timeslot -> total count
    group_timeslots = {}  # (course, group) -> timeslot
    
    # Priority queue: most conflicted groups first, then largest groups
    group_priority = []
    for course_id in course_group_students:
        for group_id, students in course_group_students[course_id].items():
            conflict_count = len(group_conflicts.get((course_id, group_id), set()))
            group_size = len(students)
            group_priority.append((course_id, group_id, conflict_count, group_size, students))
    
    group_priority.sort(key=lambda x: (-x[2], -x[3]))  # conflicts desc, size desc
    
    # Assign each group to a timeslot
    current_timeslot = 0
    
    for course_id, group_id, conflict_count, group_size, group_students in group_priority:
        best_timeslot = None
        
        # Try existing timeslots first
        for ts in range(current_timeslot + 1):
            # Check capacity
            if timeslot_student_counts[ts] + group_size > max_students_per_timeslot:
                continue
            
            # Check for student overlap (CRITICAL FIX)
            if timeslot_students[ts] & group_students:
                continue
            
            # Check for group conflicts
            has_conflict = False
            for existing_course, existing_groups in timeslot_assignments[ts].items():
                for existing_group in existing_groups:
                    if (course_id, group_id) in group_conflicts and (existing_course, existing_group) in group_conflicts[(course_id, group_id)]:
                        has_conflict = True
                        break
                if has_conflict:
                    break
            
            if not has_conflict:
                best_timeslot = ts
                break
        
        # If no existing timeslot works, create new one
        if best_timeslot is None:
            best_timeslot = current_timeslot
            current_timeslot += 1
        
        # Assign group to timeslot
        timeslot_assignments[best_timeslot][course_id].append(group_id)
        timeslot_students[best_timeslot].update(group_students)
        timeslot_student_counts[best_timeslot] += group_size
        group_timeslots[(course_id, group_id)] = best_timeslot
    
    # Apply adjacency optimization for split courses
    optimize_timeslot_adjacency(timeslot_assignments, timeslot_student_counts, timeslot_students, 
                              max_students_per_timeslot, course_group_students, group_conflicts)
    
    # Convert to required output format
    compatible_groups = []
    for timeslot in sorted(timeslot_assignments.keys()):
        courses_in_slot = []
        total_students = 0
        
        for course_id, group_ids in timeslot_assignments[timeslot].items():
            course_student_count = sum(course_group_sizes[course_id][group_id] for group_id in group_ids)
            total_students += course_student_count
            
            courses_in_slot.append({
                "course_id": course_id,
                "groups": group_ids,
                "student_count": course_student_count,
                "all_groups_scheduled_together": len(group_ids) == len(course_group_students[course_id]),
                "split_course": len(group_ids) < len(course_group_students[course_id])
            })
        
        compatible_groups.append({
            "timeslot": timeslot + 1,
            "courses": courses_in_slot,
            "student_count": total_students,
            "within_capacity": total_students <= max_students_per_timeslot
        })
    
    compatible_groups.sort(key=lambda x: x["timeslot"])
    
    return compatible_groups, course_conflicts


def optimize_timeslot_adjacency(timeslot_assignments, timeslot_student_counts, timeslot_students, 
                              max_capacity, course_group_students, group_conflicts):
    """Optimize timeslot arrangement to keep split courses adjacent"""
    # Find courses split across multiple timeslots
    course_timeslots = defaultdict(set)
    for timeslot, courses in timeslot_assignments.items():
        for course_id in courses:
            course_timeslots[course_id].add(timeslot)
    
    split_courses = {course: slots for course, slots in course_timeslots.items() if len(slots) > 1}
    
    if not split_courses:
        return
    
    # For each split course, try to compact its timeslots
    for course_id, original_slots in split_courses.items():
        original_slots_list = sorted(list(original_slots))
        current_spread = max(original_slots_list) - min(original_slots_list)
        
        if current_spread <= 1:  # Already adjacent
            continue
        
        # Try to find consecutive slots that can accommodate all groups
        min_slots_needed = len(original_slots_list)
        max_timeslot = max(timeslot_assignments.keys()) if timeslot_assignments else 0
        
        for start_slot in range(max_timeslot - min_slots_needed + 2):
            target_slots = list(range(start_slot, start_slot + min_slots_needed))
            
            if can_rearrange_groups(course_id, original_slots_list, target_slots, 
                                  timeslot_assignments, timeslot_student_counts, timeslot_students,
                                  max_capacity, course_group_students, group_conflicts):
                new_spread = max(target_slots) - min(target_slots)
                if new_spread < current_spread:
                    perform_group_rearrangement(course_id, original_slots_list, target_slots,
                                              timeslot_assignments, timeslot_student_counts, 
                                              timeslot_students, course_group_students)
                    break


def can_rearrange_groups(course_id, source_slots, target_slots, timeslot_assignments, 
                        timeslot_student_counts, timeslot_students, max_capacity, 
                        course_group_students, group_conflicts):
    """Check if course groups can be moved to target slots without conflicts"""
    # Get all groups to move
    groups_to_move = []
    for slot in source_slots:
        if course_id in timeslot_assignments[slot]:
            for group_id in timeslot_assignments[slot][course_id]:
                groups_to_move.append((group_id, slot))
    
    # Simulate the move
    for i, (group_id, original_slot) in enumerate(groups_to_move):
        if i >= len(target_slots):
            return False
            
        target_slot = target_slots[i]
        if target_slot == original_slot:
            continue
        
        group_students = course_group_students[course_id][group_id]
        group_size = len(group_students)
        
        # Check capacity
        new_load = timeslot_student_counts.get(target_slot, 0) + group_size
        if new_load > max_capacity:
            return False
        
        # Check student conflicts
        if timeslot_students.get(target_slot, set()) & group_students:
            return False
        
        # Check group conflicts
        for existing_course, existing_groups in timeslot_assignments.get(target_slot, {}).items():
            for existing_group in existing_groups:
                if (course_id, group_id) in group_conflicts and (existing_course, existing_group) in group_conflicts[(course_id, group_id)]:
                    return False
    
    return True


def perform_group_rearrangement(course_id, source_slots, target_slots, timeslot_assignments, 
                               timeslot_student_counts, timeslot_students, course_group_students):
    """Move groups from source slots to target slots"""
    # Collect all groups to move
    groups_to_move = []
    for slot in source_slots:
        if course_id in timeslot_assignments[slot]:
            for group_id in timeslot_assignments[slot][course_id]:
                groups_to_move.append((group_id, slot))
    
    # Remove from original slots
    for group_id, original_slot in groups_to_move:
        if course_id in timeslot_assignments[original_slot] and group_id in timeslot_assignments[original_slot][course_id]:
            timeslot_assignments[original_slot][course_id].remove(group_id)
            group_students = course_group_students[course_id][group_id]
            timeslot_student_counts[original_slot] -= len(group_students)
            timeslot_students[original_slot] -= group_students
            
            # Clean up empty entries
            if not timeslot_assignments[original_slot][course_id]:
                del timeslot_assignments[original_slot][course_id]
            if not timeslot_assignments[original_slot]:
                if original_slot in timeslot_assignments:
                    del timeslot_assignments[original_slot]
                if original_slot in timeslot_student_counts:
                    del timeslot_student_counts[original_slot]
                if original_slot in timeslot_students:
                    del timeslot_students[original_slot]
    
    # Add to target slots
    for i, (group_id, _) in enumerate(groups_to_move):
        if i >= len(target_slots):
            break
            
        target_slot = target_slots[i]
        
        # Initialize target slot if needed
        if target_slot not in timeslot_assignments:
            timeslot_assignments[target_slot] = defaultdict(list)
        if target_slot not in timeslot_student_counts:
            timeslot_student_counts[target_slot] = 0
        if target_slot not in timeslot_students:
            timeslot_students[target_slot] = set()
        
        # Add group
        timeslot_assignments[target_slot][course_id].append(group_id)
        group_students = course_group_students[course_id][group_id]
        timeslot_student_counts[target_slot] += len(group_students)
        timeslot_students[target_slot].update(group_students)

 


def find_compatible_courses_with_group_optimization(courses):
    """
    Alternative approach: First try to combine groups within courses that don't conflict,
    then find compatibility between courses.
    """
    if not courses:
        return {"compatible_groups": [], "group_conflicts": defaultdict(list)}
    
    # Data structure: {course_id: {group_id: set(student_ids)}}
    course_group_students = defaultdict(lambda: defaultdict(set))
    
    # Populate enrollment data
    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].add(
            enrollment.student_id
        )
    
    # For each course, find which groups can be combined (no student overlap)
    course_combined_groups = {}
    
    for course_id, groups in course_group_students.items():
        group_list = list(groups.keys())
        combined_groups = []
        used_groups = set()
        
        for group_id in group_list:
            if group_id in used_groups:
                continue
                
            # Start a new combined group
            current_combination = [group_id]
            current_students = groups[group_id].copy()
            used_groups.add(group_id)
            
            # Try to add more groups that don't conflict
            for other_group in group_list:
                if other_group in used_groups:
                    continue
                    
                other_students = groups[other_group]
                if not (current_students & other_students):  # No overlap
                    current_combination.append(other_group)
                    current_students.update(other_students)
                    used_groups.add(other_group)
            
            combined_groups.append({
                'groups': current_combination,
                'students': current_students
            })
        
        course_combined_groups[course_id] = combined_groups
    
    # Now find compatibility between course combinations
    all_course_combinations = []
    for course_id, combinations_list in course_combined_groups.items():
        for i, combo in enumerate(combinations_list):
            all_course_combinations.append((course_id, i, combo))
    
    # Build conflict graph between course combinations
    combination_conflicts = defaultdict(list)
    for (course1, combo1_idx, combo1), (course2, combo2_idx, combo2) in combinations(all_course_combinations, 2):
        if combo1['students'] & combo2['students']:  # Student overlap
            key1 = (course1, combo1_idx)
            key2 = (course2, combo2_idx)
            combination_conflicts[key1].append(key2)
            combination_conflicts[key2].append(key1)
    
    # Greedy coloring
    color_combinations = defaultdict(list)
    colored = {}
    combination_list = sorted(all_course_combinations, 
                            key=lambda x: -len(combination_conflicts[(x[0], x[1])]))
    
    for course_id, combo_idx, combo in combination_list:
        key = (course_id, combo_idx)
        
        # Find used colors
        used_colors = {
            colored[conflict]
            for conflict in combination_conflicts[key]
            if conflict in colored
        }
        
        # Assign first available color
        for color in range(len(all_course_combinations)):
            if color not in used_colors:
                colored[key] = color
                color_combinations[color].append((course_id, combo_idx, combo))
                break
    
    # Convert to output format
    compatible_groups = []
    for color, combinations_in_slot in color_combinations.items():
        course_details = []
        total_students = 0
        
        for course_id, combo_idx, combo in combinations_in_slot:
            course_details.append({
                "course_id": course_id,
                "groups": combo['groups']
            })
            total_students += len(combo['students'])
        
        compatible_groups.append({
            "timeslot": color + 1,
            "courses": course_details,
            "student_count": total_students,
        })
    
    compatible_groups.sort(key=lambda x: -x["student_count"])
    
    return compatible_groups, combination_conflicts
 

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

        # Check for same-slot conflict
        same_slot_exam = StudentExam.objects.filter(
            student_id=student_id,
            exam__date=proposed_date,
            exam__start_time=course.start_time if hasattr(course, "start_time") else None,
            exam__end_time=course.end_time if hasattr(course, "end_time") else None,
        ).exists()
        if same_slot_exam:
            conflicts.append(
            f"Student {student_id} already has an exam in the same slot on {proposed_date}"
            )
            continue

       

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


def get_exam_time_for_group(weekday, available_slots, available_seats=None, slots_usage=None, needed_steats=None):
    
    if weekday== "Saturday":
        return None
    
    for slot, number in slots_usage.items():
        if number+needed_steats<= available_seats  :
            return slot
    return None
 


def fetch_courses(course_ids):
    if course_ids:
        return {c.id: c for c in Course.objects.filter(id__in=course_ids)}
    # else fetch all courses with enrollments
    courses_qs = Course.objects.annotate(enrollment_count=Count("enrollments")).filter(enrollment_count__gt=0)
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
    enrollments_qs = Enrollment.objects.filter(
        group_id__in=course_group_ids
    ).select_related('student').values('group_id', 'student_id')
    enrollments_by_group = defaultdict(list)
    for enrollment in enrollments_qs:
        enrollments_by_group[enrollment['group_id']].append(enrollment['student_id'])
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
     slot_seats_usage
):
  
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
            slot_name = get_exam_time_for_group( weekday, all_slots, all_available_seats,slot_seats_usage, needed_seats )
            print(slot_name)
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
                    StudentExam(student_id=student_id, exam=exam) for student_id in student_ids
                ]
                StudentExam.objects.bulk_create(student_exam_objs)

                slot_seats_usage[slot_name] += needed_seats
                logger.debug(f"Scheduled course {course_id}, group {group_id} at {start_time}–{end_time}")

            except Exception as e:
                logger.error(f"Failed to create exam for course {course_id}, group {group_id}: {e}")
                unscheduled_reasons[group_id] = str(e)
                partially_scheduled = True
                remaining_groups.append(group_id)

        # Update groups for this course to only those not scheduled
        course_dict["groups"] = remaining_groups

    # Clean courses with no groups left
    course_group["courses"] = [c for c in course_group["courses"] if c["groups"]]
    

    return exams_created, partially_scheduled, unscheduled_reasons

 


def schedule_unscheduled_group(course_id, group_id):
    try:
        # Fetch enrolled student IDs once
        enrolled_students = set(
            Enrollment.objects.filter(course_id=course_id, group_id=group_id)
            .values_list("student_id", flat=True)
        )
        if not enrolled_students:
            print(f"No students enrolled in course {course_id}, group {group_id}")
            return False

        # Get exam date range once
        exam_dates = Exam.objects.aggregate(
            min_date=Min("date"),
            max_date=Max("date")
        )
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

            location = Enrollment.objects.filter(course_id=course_id, group_id=group_id).first().course.department.location

            # FIXED: Proper room capacity checking without the non-existent function
            rooms = Room.objects.filter(location=location)
            if not rooms:
                print(f"No rooms available at location {location}")
                continue
            
            # Calculate total room capacity
            total_room_capacity = sum(room.capacity for room in rooms)
            
            # Calculate students already scheduled in this slot and date
            existing_exams = Exam.objects.filter(
                date=current_date, slot_name=slot_name
            )
            
            # Count unique students already scheduled
            existing_student_ids = set()
            for exam in existing_exams:
                exam_students = Enrollment.objects.filter(
                    course_id=exam.group.course_id, 
                    group_id=exam.group_id
                ).values_list('student_id', flat=True)
                existing_student_ids.update(exam_students)
            
            existing_students_count = len(existing_student_ids)
            new_students_count = len(enrolled_students)
            
            # Check if total capacity can accommodate all students
            if existing_students_count + new_students_count > total_room_capacity:
                print(f"Not enough room capacity for course {course_id}, group {group_id} on {current_date} in {slot_name} slot")
                continue

            # Create exam and student exams
            exam = Exam.objects.create(
                date=current_date,
                start_time=start_time,
                end_time=end_time,
                group=group,
                slot_name=slot_name,
            )
            student_exams = StudentExam.objects.bulk_create([
                StudentExam(student_id=sid, exam=exam) for sid in enrolled_students
            ])
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
        raise Exception(f"Not enough room capacity: {total_students} students vs {total_capacity} capacity")

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
                print(f"Warning: Unknown slot name '{slot_name}' for student {se.student.id}")

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
                                
                                if total_fill > max_fill and total_fill <= available_capacity:
                                    best_pair = (exam1, exam2, size1, size2)
                                    max_fill = total_fill

                    if best_pair:
                        # Allocate the best pair found
                        exam1, exam2, size1, size2 = best_pair
                        assigned = []

                        # Assign students from first exam
                        exam1_students = [se for se in remaining_students if se.exam == exam1][:size1]
                        assigned.extend(exam1_students)
                        for se in exam1_students:
                            remaining_students.remove(se)
                            exams[exam1].remove(se)

                        # Assign students from second exam
                        exam2_students = [se for se in remaining_students if se.exam == exam2][:size2]
                        assigned.extend(exam2_students)
                        for se in exam2_students:
                            remaining_students.remove(se)
                            exams[exam2].remove(se)

                        schedule[date][slot_name][room.id].extend(assigned)

                    else:
                        # No suitable pair found, try to assign a single exam
                        # Find the smallest exam that can fit in the room
                        smallest_exam = None
                        smallest_size = float('inf')
                        
                        for exam, students in sorted_exams:
                            if students and len(students) <= available_capacity and len(students) < smallest_size:
                                smallest_exam = exam
                                smallest_size = len(students)
                        
                        if smallest_exam:
                            to_assign = [se for se in remaining_students if se.exam == smallest_exam][:available_capacity]
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
                    StudentExam.objects.filter(id__in=student_exam_ids).update(room_id=room_id)

        # Final attempt to assign any leftover students to any available room space
        if unaccommodated:
            remaining_student_exams = StudentExam.objects.filter(
                student__in=unaccommodated,
                room__isnull=True
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

                            # sem1 = int(exam1.group.course.semester.name.split()[1])
                            # sem2 = int(exam2.group.course.semester.name.split()[1])
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




def schedule_unscheduled_group(course_id, group_id):
    try:
        # Fetch enrolled student IDs once
        enrolled_students = set(
            Enrollment.objects.filter(course_id=course_id, group_id=group_id)
            .values_list("student_id", flat=True)
        )
        if not enrolled_students:
            print(f"No students enrolled in course {course_id}, group {group_id}")
            return False

        # Get exam date range once
        exam_dates = Exam.objects.aggregate(
            min_date=Min("date"),
            max_date=Max("date")
        )
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

            # Check if can schedule course group on any of the free slots
            can_schedule, _ = can_schedule_course_group_on_slot(
                group_id, course_id, current_date, student_exams_map
            )
            if not can_schedule:
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

            location = Enrollment.objects.filter(course_id=course_id, group_id=group_id).first().course.department.location

            slot_capacity = Room.objects.filter(location=location).aggregate(
                total_capacity=Sum("capacity")
            )["total_capacity"] or 0

            # FIXED: Calculate actual students already scheduled in this exact slot and date
            existing_student_exams = StudentExam.objects.filter(
                exam__date=current_date,
                exam__start_time=start_time,
                exam__end_time=end_time,
                exam__group__course__department__location=location
            )
            existing_students_count = existing_student_exams.count()

            total_students = existing_students_count + len(enrolled_students)
            if total_students > slot_capacity:
                print(f"Not enough room capacity for course {course_id}, group {group_id} on {current_date} in {slot_name} slot")
                continue

            # Create exam and student exams
            exam = Exam.objects.create(
                date=current_date,
                start_time=start_time,
                end_time=end_time,
                group=group,
                slot_name=slot_name,
            )
            student_exams = StudentExam.objects.bulk_create([
                StudentExam(student_id=sid, exam=exam) for sid in enrolled_students
            ])
            
            # FIXED: Pass the new exam info to allocation function
            success = allocate_shared_rooms_updated(student_exams, location, current_date, start_time, end_time)
            if not success:
                # If room allocation fails, rollback the exam creation
                exam.delete()
                print(f"Failed to allocate rooms for course {course_id}, group {group_id} on {current_date}")
                continue

            print(f"Scheduled course {course_id}, group {group_id} on {current_date}")
            return True

        # If no suitable date found
        return False

    except Exception as e:
        print(f"Error scheduling course {course_id}, group {group_id}: {e}")
        return False


def allocate_shared_rooms_updated(student_exams, location=None, exam_date=None, start_time=None, end_time=None):
    """
    Allocate rooms for student exams with proper capacity checking.
    Returns True if all students were accommodated, False otherwise.
    """
    if not student_exams:
        return True
    
    # Get location from student exams if not provided
    if location is None:
        location = student_exams[0].exam.group.course.department.location
    
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
        # Get current room occupancy for this time slot
        room_occupancy = {}
        for room in rooms:
            # Count students already assigned to this room at this time
            occupied_count = StudentExam.objects.filter(
                room=room,
                exam__date=exam_date or student_exams[0].exam.date,
                exam__start_time=start_time or student_exams[0].exam.start_time,
                exam__end_time=end_time or student_exams[0].exam.end_time
            ).count()
            room_occupancy[room.id] = {
                'occupied': occupied_count,
                'available': room.capacity - occupied_count,
                'room': room
            }

        # Organize students by exam
        exams_students = defaultdict(list)
        for se in student_exams:
            exams_students[se.exam].append(se)

        # Sort exams by size (largest first for better packing)
        sorted_exams = sorted(exams_students.items(), key=lambda x: -len(x[1]))

        unassigned_students = []
        
        # Try to assign each exam to available rooms
        for exam, students in sorted_exams:
            students_to_assign = students.copy()
            
            # Try to fit this exam in available rooms
            for room_id, room_info in sorted(room_occupancy.items(), key=lambda x: -x[1]['available']):
                if not students_to_assign or room_info['available'] <= 0:
                    continue
                    
                # Assign as many students as possible to this room
                can_assign = min(len(students_to_assign), room_info['available'])
                assigned_students = students_to_assign[:can_assign]
                
                # Update database
                StudentExam.objects.filter(
                    id__in=[se.id for se in assigned_students]
                ).update(room_id=room_id)
                
                # Update tracking
                students_to_assign = students_to_assign[can_assign:]
                room_occupancy[room_id]['occupied'] += can_assign
                room_occupancy[room_id]['available'] -= can_assign
                
                print(f"Assigned {can_assign} students from exam {exam.id} to room {room_info['room'].name}")
            
            # Track any students that couldn't be assigned
            unassigned_students.extend(students_to_assign)

        # Final attempt for any remaining students (one by one)
        for se in unassigned_students:
            assigned = False
            for room_id, room_info in room_occupancy.items():
                if room_info['available'] > 0:
                    se.room_id = room_id
                    se.save()
                    room_occupancy[room_id]['occupied'] += 1
                    room_occupancy[room_id]['available'] -= 1
                    assigned = True
                    break
            
            if not assigned:
                print(f"Could not assign student {se.student_id} to any room")
                return False

        print(f"Successfully allocated all {len(student_exams)} students to rooms")
        return True


# Optional: Add a verification function
def verify_room_capacity():
    """
    Verify that no rooms are over capacity.
    Returns a list of violations.
    """
    violations = []
    
    # Group by exam details to check each time slot
    exams = Exam.objects.all()
    
    for exam in exams:
        location = exam.group.course.department.location
        rooms = Room.objects.filter(location=location)
        
        for room in rooms:
            # Count students in this room at this exact time
            student_count = StudentExam.objects.filter(
                room=room,
                exam__date=exam.date,
                exam__start_time=exam.start_time,
                exam__end_time=exam.end_time
            ).count()
            
            if student_count > room.capacity:
                violations.append({
                    'room': room.name,
                    'capacity': room.capacity,
                    'assigned': student_count,
                    'overflow': student_count - room.capacity,
                    'date': exam.date,
                    'time': f"{exam.start_time}-{exam.end_time}"
                })
    
    return violations



def allocate_shared_rooms(location_id):
    """
    Enhanced room allocation that efficiently packs students into rooms
    using a best-fit decreasing algorithm to minimize overflow and skipped slots.
    """
    # Get all unassigned student exams with related data
    student_exams = (
        StudentExam.objects.filter(room__isnull=True)
        .select_related("exam", "exam__group__course", "student")
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
        # Create a comprehensive schedule structure
        # {date: {slot_name: {room_id: [student_exams]}}}
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
                
                # Group students by exam (course)
                exams = defaultdict(list)
                for se in slot_students:
                    exams[se.exam].append(se)
                
                # Create list of exams with their student counts
                exam_list = [(exam, students) for exam, students in exams.items() if students]
                
                # Sort exams by number of students (largest first for better packing)
                exam_list.sort(key=lambda x: len(x[1]), reverse=True)
                
                remaining_students = slot_students.copy()
                total_students = len(remaining_students)
                total_capacity = sum(room.capacity for room in rooms)
                
                # If total capacity is insufficient, some students will remain unaccommodated
                if total_students > total_capacity:
                    # We'll handle this below by packing as many as possible
                    pass
                
                # Initialize room occupancy for this slot
                room_occupancy = {room.id: 0 for room in rooms}
                
                # First, try to assign complete exams to rooms using best-fit decreasing
                for exam, exam_students in exam_list:
                    exam_size = len(exam_students)
                    if exam_size == 0:
                        continue
                    
                    # Find the best room (smallest room that can fit this exam)
                    best_room = None
                    best_room_size = float('inf')
                    
                    for room in rooms:
                        current_occupancy = room_occupancy[room.id]
                        available_space = room.capacity - current_occupancy
                        
                        if available_space >= exam_size and room.capacity < best_room_size:
                            best_room = room
                            best_room_size = room.capacity
                    
                    # If no single room can fit the entire exam, split it
                    if best_room is None:
                        # Split the exam across multiple rooms
                        students_to_assign = exam_students.copy()
                        
                        # Sort rooms by available space (largest available space first)
                        sorted_rooms = sorted(
                            rooms, 
                            key=lambda r: r.capacity - room_occupancy[r.id], 
                            reverse=True
                        )
                        
                        for room in sorted_rooms:
                            if not students_to_assign:
                                break
                            
                            available_space = room.capacity - room_occupancy[room.id]
                            if available_space <= 0:
                                continue
                            
                            # Assign as many students as possible to this room
                            assign_count = min(len(students_to_assign), available_space)
                            assigned_students = students_to_assign[:assign_count]
                            
                            # Update schedule and occupancy
                            schedule[date][slot_name][room.id].extend(assigned_students)
                            room_occupancy[room.id] += assign_count
                            
                            # Remove assigned students
                            for se in assigned_students:
                                if se in remaining_students:
                                    remaining_students.remove(se)
                            
                            students_to_assign = students_to_assign[assign_count:]
                        
                        # Any remaining students will be handled in the final pass
                        continue
                    
                    # Assign the entire exam to the best room
                    schedule[date][slot_name][best_room.id].extend(exam_students)
                    room_occupancy[best_room.id] += exam_size
                    
                    # Remove assigned students from remaining
                    for se in exam_students:
                        if se in remaining_students:
                            remaining_students.remove(se)
                
                # Second pass: assign any remaining students (from split exams)
                # Sort rooms by available space (largest available space first)
                sorted_rooms = sorted(
                    rooms, 
                    key=lambda r: r.capacity - room_occupancy[r.id], 
                    reverse=True
                )
                
                for se in remaining_students.copy():
                    assigned = False
                    for room in sorted_rooms:
                        available_space = room.capacity - room_occupancy[room.id]
                        if available_space > 0:
                            schedule[date][slot_name][room.id].append(se)
                            room_occupancy[room.id] += 1
                            remaining_students.remove(se)
                            assigned = True
                            break
                    
                    if not assigned:
                        unaccommodated.append(se.student)
        
        # Save all assignments to DB
        for date, slots in schedule.items():
            for slot_name, room_assignments in slots.items():
                for room_id, student_exams_list in room_assignments.items():
                    StudentExam.objects.filter(
                        id__in=[se.id for se in student_exams_list]
                    ).update(room_id=room_id)
        
        # Final attempt for leftover students
        if unaccommodated:
            remaining_exams = StudentExam.objects.filter(
                student__in=unaccommodated, room__isnull=True
            ).select_related("exam")
            
            for se in remaining_exams:
                date = se.exam.date
                slot_name = se.exam.slot_name
                
                # Try to find any room with available capacity
                for room in rooms:
                    # Count current occupancy in this room for this slot
                    current_occupancy = StudentExam.objects.filter(
                        room_id=room.id,
                        exam__date=date,
                        exam__slot_name=slot_name
                    ).count()
                    
                    if current_occupancy < room.capacity:
                        se.room = room
                        se.save()
                        try:
                            unaccommodated.remove(se.student)
                        except ValueError:
                            pass
                        break
    
    return unaccommodated


def generate_exam_schedule(slots=None, course_ids=None, master_timetable: MasterTimetable = None, location=None):
    """
    Enhanced exam schedule generator that efficiently utilizes available slots
    and rooms by implementing a more sophisticated packing algorithm.
    """
    try:
        courses_dict = fetch_courses(course_ids)
        enrolled_course_ids = list(courses_dict.keys())
        compatible_groups, _ = find_compatible_courses_within_group(enrolled_course_ids)
        pprint(compatible_groups)
        unscheduled_reasons = {}
     
        if not compatible_groups:
            logger.info("No compatible course groups found")
            return [], "No compatible course groups found", [], {}
        
        slots_by_date = get_slots_by_date(slots)
        # Get all available dates (excluding Saturdays) and sort them
        dates = sorted(date for date in slots_by_date if date.strftime("%A") != "Saturday")
        logger.info(f"dates: {str(dates)}")
        
        if not dates:
            logger.info("No available dates (excluding Saturdays)")
            # populate unscheduled reasons for all groups
            for group in compatible_groups:
                for course in group["courses"]:
                    for group_id in course["groups"]:
                        unscheduled_reasons[group_id] = "No available dates (excluding Saturdays)"
            return [], [], compatible_groups, unscheduled_reasons
        
        total_seats = Room.objects.filter(location_id=location).aggregate(total=Sum("capacity"))["total"] or 0
        logger.info(f"Total compatible groups to schedule: {len(compatible_groups)}")
        logger.info(f"Available seats: {total_seats}")
        
        enrollments_by_group = prefetch_enrollments(compatible_groups)
        all_group_ids = set()
        for group in compatible_groups:
            for course in group["courses"]:
                all_group_ids.update(course["groups"])
        groups_dict = fetch_course_groups(all_group_ids)
        
        exams_created = []
        unscheduled_groups = []
        
        with transaction.atomic():
            slot_cache = {}
            for date in dates:
                slot_cache[date] = {slot["name"]: slot for slot in slots_by_date[date]}
            
            # Create a copy of compatible_groups to work with
            remaining_groups = copy.deepcopy(compatible_groups)
            remaining_days=copy.deepcopy(dates)
            
            # Process each date
            for date_idx, current_date in enumerate(dates):
                if not remaining_groups:
                     
                    break
                
                weekday = current_date.strftime("%A")
                slot_map = slot_cache[current_date]
                all_slots = set(slot_map.keys())
                
                # Track seat usage for this date
                slot_seats_usage = {"Morning": 0, "Evening": 0, "Afternoon": 0}
                
                # Calculate current occupancy for each slot on this date
                for slot_name in slot_seats_usage.keys():
                    if slot_name in all_slots:  # Only check if slot is available this day
                        existing_exams = Exam.objects.filter(
                            date=current_date, 
                            slot_name=slot_name
                        ).select_related('group')
                        
                        for exam in existing_exams:
                            # Count students in this exam
                            student_count = Enrollment.objects.filter(
                                course_id=exam.group.course_id,
                                group_id=exam.group_id
                            ).count()
                            slot_seats_usage[slot_name] += student_count
                
                # Try to schedule as many groups as possible on this date
                groups_scheduled_today = []
                
                # Sort remaining groups by total students (smallest first to maximize packing)
                remaining_groups.sort(key=lambda g: sum(course["student_count"] for course in g["courses"]))
                
                for group_idx, course_group in enumerate(remaining_groups[date_idx]):  # Copy for safe iteration
                    total_students_needed = sum(course["student_count"] for course in course_group["courses"])
                    
                    # Check if we can fit this group in any slot today
                    suitable_slot = None
                    for slot_name in all_slots:
                        if slot_seats_usage[slot_name] + total_students_needed <= total_seats:
                            suitable_slot = slot_name
                            break
                    
                    if suitable_slot is None:
                        continue  # Try next group
                    
                    # Schedule this group
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
                        slot_seats_usage
                    )
                    
                    exams_created.extend(group_exams)
                    
                    if not partially_scheduled and not any(course["groups"] for course in course_group["courses"]):
                        # Fully scheduled
                        groups_scheduled_today.append(group_idx)
                        logger.info(f"Group fully scheduled on {current_date}")
                    else:
                        # Partially scheduled or couldn't schedule
                        unscheduled_groups.append(course_group)
                        for k, v in reasons.items():
                            if k not in unscheduled_reasons:
                                unscheduled_reasons[k] = v
                        logger.info(f"Group partially scheduled on {current_date}")
                
                # Remove fully scheduled groups from remaining_groups
                # We need to remove from the end to avoid index issues
                groups_scheduled_today.sort(reverse=True)
                for idx in groups_scheduled_today:
                    if idx < len(remaining_groups):
                        remaining_groups.pop(idx)
                remaining_days.pop(date_idx)

            
            
            # Handle any remaining groups that couldn't be scheduled
            for group in remaining_groups:
                unscheduled_groups.append(group)
                for course in group["courses"]:
                    for group_id in course["groups"]:
                        if group_id not in unscheduled_reasons:
                            unscheduled_reasons[group_id] = "No suitable slot found within date range"
            
            try:
                unaccommodated_students = allocate_shared_rooms(location)
            except Exception as e:
                logger.error(f"Error in room allocation: {e}")
                unaccommodated_students = []
        
        if exams_created:
            send_exam_data.delay(
                {
                    "scheduled": len(compatible_groups) - len(unscheduled_groups),
                    "all_exams": len(compatible_groups),
                },
                user_id=1,
                broadcast=True,
            )
        
        logger.info(f"Scheduling Summary: Created {len(exams_created)} exams, {len(unscheduled_groups)} groups unscheduled.")
        return exams_created, unaccommodated_students, unscheduled_groups, unscheduled_reasons
        
    except Exception as e:
        logger.error(f"Error generating schedule: {e}")
        return [], f"Error generating schedule: {e}", [], {}


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
    slot_seats_usage
):
    """
    Enhanced version that tries multiple slots to find the best fit for each group.
    """
    exams_created = []
    unscheduled_reasons = {}
    partially_scheduled = False
    
    # Sort courses by number of students (smallest first for better packing)
    course_group["courses"].sort(key=lambda x: x.get("student_count", 0))
    
    for course_idx, course_dict in enumerate(course_group["courses"]):
        course_id = course_dict["course_id"]
        if course_id not in courses_dict:
            logger.warning(f"Course with id {course_id} not found")
            continue
        
        course = courses_dict[course_id]
        remaining_groups = []
        
        # Sort groups by size (smallest first for better packing)
        group_sizes = []
        for group_id in course_dict["groups"]:
            if group_id not in groups_dict:
                logger.warning(f"Group with id {group_id} not found")
                continue
            
            student_ids = enrollments_by_group.get(group_id, [])
            group_sizes.append((group_id, len(student_ids)))
        
        # Sort by size (smallest first)
        group_sizes.sort(key=lambda x: x[1])
        
        for group_id, needed_seats in group_sizes:
            if group_id not in groups_dict:
                continue
            
            group = groups_dict[group_id]
            student_ids = enrollments_by_group.get(group_id, [])
            
            if not student_ids:
                logger.info(f"No enrollments found for group {group_id}")
                unscheduled_reasons[group_id] = "No enrolled students"
                partially_scheduled = True
                remaining_groups.append(group_id)
                continue
            
            # Try to find the best slot for this group
            best_slot = None
            min_remaining_capacity = float('inf')
            
            for slot_name in all_slots:
                if slot_name not in slot_map:
                    continue
                
                # Check if adding this group would exceed capacity
                if slot_seats_usage[slot_name] + needed_seats > all_available_seats:
                    continue
                
                # Calculate remaining capacity after adding this group
                remaining_capacity = all_available_seats - (slot_seats_usage[slot_name] + needed_seats)
                
                # Choose slot that leaves the least remaining capacity (best fit)
                if remaining_capacity < min_remaining_capacity:
                    best_slot = slot_name
                    min_remaining_capacity = remaining_capacity
            
            if best_slot is None:
                reason = f"Not enough seats for course {course_id}, group {group_id} on {current_date}"
                logger.info(reason)
                unscheduled_reasons[group_id] = reason
                partially_scheduled = True
                remaining_groups.append(group_id)
                continue
            
            # Use the best slot found
            wanted_slot = slot_map[best_slot]
            start_time = time(*map(int, wanted_slot["start"].split(":")))
            end_time = time(*map(int, wanted_slot["end"].split(":")))
            
            try:
                exam = Exam.objects.create(
                    date=current_date,
                    start_time=start_time,
                    end_time=end_time,
                    group=group,
                    slot_name=best_slot,
                )
                master_timetable.exams.add(exam)
                exams_created.append(exam)
                
                student_exam_objs = [
                    StudentExam(student_id=student_id, exam=exam) for student_id in student_ids
                ]
                StudentExam.objects.bulk_create(student_exam_objs)
                
                # Update slot usage
                slot_seats_usage[best_slot] += needed_seats
                
                logger.debug(f"Scheduled course {course_id}, group {group_id} at {start_time}â€“{end_time} in slot {best_slot}")
                
            except Exception as e:
                logger.error(f"Failed to create exam for course {course_id}, group {group_id}: {e}")
                unscheduled_reasons[group_id] = str(e)
                partially_scheduled = True
                remaining_groups.append(group_id)
        
        # Update groups for this course to only those not scheduled
        course_dict["groups"] = remaining_groups
    
    # Clean courses with no groups left
    course_group["courses"] = [c for c in course_group["courses"] if c["groups"]]
    
    return exams_created, partially_scheduled, unscheduled_reasons






 





 