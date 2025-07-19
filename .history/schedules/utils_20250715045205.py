from datetime import timedelta, time
from collections import defaultdict
import random
from django.db import transaction
from django.utils.timezone import now
from django.db.models import Sum

from courses.models import Course
from exams.models import Exam, StudentExam
from enrollments.models import Enrollment
from rooms.models import Room
from django.db.models import Count
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


 
def get_exam_slots(start_date, max_slots=None):
    """
    Generate a list of available exam slots starting from a given date.
    Each slot is a tuple of (date, label, start_time, end_time)
    """
    date_slots = []
    current_date = start_date

    while max_slots is None or len(date_slots) < max_slots:
        weekday = current_date.strftime('%A')
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
                if max_slots and len(date_slots) >= max_slots:
                    break
        current_date += timedelta(days=1)

    return date_slots

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
    
    # Add any courses that don't appear in the conflict matrix
    for course in enrolled_courses.values_list('id', flat=True):
        all_courses.add(course)
    
    # Build adjacency list for course compatibility graph
    # Two courses are compatible if they don't share any students
    compatibility_graph = {course: set() for course in all_courses}
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if pair not in course_conflict_matrix or course_conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    # Group compatible courses using a greedy algorithm
    remaining_courses = set(all_courses)
    course_groups = []
    
    while remaining_courses:
        # Start a new group
        course_group = []
        
        # Pick a course with the fewest compatible options
        if remaining_courses:
            course1 = min(
                [c for c in remaining_courses],
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) \
                    if len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) > 0 \
                    else float('inf')
            )
            
            course_group.append(course1)
            remaining_courses.remove(course1)
            
            # Keep track of courses that are compatible with ALL courses in our group
            compatible_with_group = set(compatibility_graph[course1]) & remaining_courses
            
            # Add more courses to the group if possible (greedy approach)
            while compatible_with_group and len(course_group) < 10:  # Limit to 10 courses per group for practical reasons
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

def student_course_assignment(course_pairs):
    """
    For each student, determine which courses they're enrolled in from the given pairs
    Returns a mapping of student_id -> list of (pair_index, course_id)
    """
    student_assignments = defaultdict(list)
    
    for pair_index, pair in enumerate(course_pairs):
        for course_id in pair:
            enrollments = Enrollment.objects.filter(course_id=course_id)
            for enrollment in enrollments:
                student_assignments[enrollment.student_id].append((pair_index, course_id))
    
    return student_assignments

def detect_scheduling_conflicts(course_pairs, student_assignments, date_slots):
    """
    Detect potential scheduling conflicts for each pair and slot
    Returns a conflict score for each combination of pair and slot
    Lower scores are better (fewer conflicts)
    """
    num_pairs = len(course_pairs)
    num_slots = len(date_slots)
    
    # Initialize conflict matrix
    conflict_scores = [[0 for _ in range(num_slots)] for _ in range(num_pairs)]
    
    # Group slots by date
    slots_by_date = defaultdict(list)
    for slot_idx, (date, label, start, end) in enumerate(date_slots):
        slots_by_date[date].append(slot_idx)
    
    # Calculate conflicts
    for student_id, assignments in student_assignments.items():
        # Check if student has multiple exams on the same day
        for pair_indices, course_ids in assignments:
            for pair_idx1, _ in assignments:
                if pair_idx1 != pair_indices:
                    # These two course pairs can't be scheduled on the same day
                    for date, slot_indices in slots_by_date.items():
                        for slot_idx1 in slot_indices:
                            for slot_idx2 in slot_indices:
                                conflict_scores[pair_idx1][slot_idx1] += 1
                                conflict_scores[pair_indices][slot_idx2] += 1
    
    return conflict_scores

def calculate_room_requirements(course_pairs):
    """
    Calculate how many students need to be accommodated for each course pair
    Returns a list of dictionaries with course_id -> student_count
    """
    room_requirements = []
    
    for pair in course_pairs:
        pair_requirements = {}
        for course_id in pair:
            student_count = Enrollment.objects.filter(course_id=course_id).count()
            pair_requirements[course_id] = student_count
        room_requirements.append(pair_requirements)
    
    return room_requirements

def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0
 

def has_day_off(student_exam_dates):
    from datetime import date, datetime
    
    if len(student_exam_dates)<2:
        return True
    try:
        date1= student_exam_dates[-2]
        date2=student_exam_dates[-1]

     
        time_difference = date2 - date1
        print(f"Dates: {date1}")
        print(time_difference)
        return time_difference.days == 2
    except ValueError as e:
        print(str(e))
        return False
def has_sufficient_gap(student_exam_dates, proposed_date, min_gap_days=2):
    """
    Check if scheduling an exam on proposed_date would maintain minimum gap
    between consecutive exams for a student.
    
    Args:
        student_exam_dates: List of dates when student has exams (sorted)
        proposed_date: The date we want to schedule a new exam
        min_gap_days: Minimum days between consecutive exams (default: 2 means 1 day off)
    
    Returns:
        bool: True if the proposed date maintains sufficient gap
    """
    if not student_exam_dates:
        return True
    
    # Add the proposed date to the list and sort
    all_dates = student_exam_dates + [proposed_date]
    all_dates.sort()
    
    # Check gaps between consecutive exams
    for i in range(len(all_dates) - 1):
        gap = (all_dates[i + 1] - all_dates[i]).days
        if gap < min_gap_days:
            return False
    
    return True


def can_schedule_on_date(course_pair, proposed_date, student_exam_dates):
    """
    Check if a course pair can be scheduled on the proposed date
    considering both same-day conflicts and day-off constraints.
    
    Args:
        course_pair: List of course IDs to be scheduled together
        proposed_date: The date to check
        student_exam_dates: Dict mapping student_id to list of their exam dates
    
    Returns:
        tuple: (can_schedule: bool, conflicts: list)
    """
    conflicts = []
    
    for course_id in course_pair:
        student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
        
        for student_id in student_ids:
            current_exam_dates = student_exam_dates.get(student_id, [])
            
            # Check for same-day conflict
            if proposed_date in current_exam_dates:
                conflicts.append(f"Student {student_id} already has exam on {proposed_date}")
                continue
            
            # Check for day-off constraint
            if not has_sufficient_gap(current_exam_dates, proposed_date):
                conflicts.append(f"Student {student_id} would not have sufficient gap before/after {proposed_date}")
    
    return len(conflicts) == 0, conflicts


def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate exam schedule with proper day-off constraints enforced.
    This replaces the original function with corrected day-off logic.
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    conflict_matrix = analyze_student_course_conflicts()
    course_pairs = find_compatible_courses(conflict_matrix)
    
    if course_ids:
        course_ids_set = set(course_ids)
        filtered_pairs = []
        for pair in course_pairs:
            filtered_pair = [c for c in pair if c in course_ids_set]
            if filtered_pair:
                filtered_pairs.append(filtered_pair)
        course_pairs = filtered_pairs
    
    # Generate more slots to accommodate day-off constraints
    # Need more slots because we can't use consecutive days
    estimated_slots_needed = len(course_pairs) * 10 # Conservative estimate
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
    
    exams_created = []
    student_exam_dates = defaultdict(list)  # student_id -> [exam_dates]
    unaccommodated_students = []
    
    with transaction.atomic():
        # Sort pairs by difficulty (most constrained first)
        pair_difficulties = []
        for i, pair in enumerate(course_pairs):
            # Calculate difficulty based on number of students and conflicts
            total_students = sum(
                Enrollment.objects.filter(course_id=course_id).count() 
                for course_id in pair
            )
            pair_difficulties.append((i, total_students))
        
        pair_difficulties.sort(key=lambda x: x[1], reverse=True)
        
        # Group slots by date for efficient lookup
        slots_by_date = defaultdict(list)
        for slot_idx, (date, label, start, end) in enumerate(date_slots):
            slots_by_date[date].append((slot_idx, label, start, end))
        
        assigned_slots = set()
        
        for pair_idx, _ in pair_difficulties:
            pair = course_pairs[pair_idx]
            
            best_slot = None
            best_date = None
            
            # Try each date in order
            for date in sorted(slots_by_date.keys()):
                # Skip if this date is already too close to other exams for any student
                can_schedule, conflicts = can_schedule_on_date(pair, date, student_exam_dates)
                
                if not can_schedule:
                    # print(f"Cannot schedule pair {pair} on {date}: {conflicts}")
                    continue
                
                # Find available slot on this date
                available_slots = [
                    (slot_idx, label, start, end) 
                    for slot_idx, label, start, end in slots_by_date[date]
                    if slot_idx not in assigned_slots
                ]
                 
                if available_slots:
                     
                    best_slot = available_slots[0]
                    best_date = date
                    break
            
            if best_slot is None:
                raise ValueError(f"Cannot find suitable slot for course pair {pair} while maintaining day-off constraints.")
            
            # Schedule the exam
            slot_idx, label, start_time, end_time = best_slot
            assigned_slots.add(slot_idx)
            
            # Create exams for all courses in the pair
            pair_exams = []
            for course_id in pair:
                course = Course.objects.get(id=course_id)
                
                exam = Exam.objects.create(
                    course=course,
                    date=best_date,
                    start_time=start_time,
                    end_time=end_time
                )
                exams_created.append(exam)
                pair_exams.append(exam)
                
                # Update student exam dates
                student_ids = Enrollment.objects.filter(course=course).values_list('student_id', flat=True)
                for student_id in student_ids:
                    student_exam_dates[student_id].append(best_date)
                    student_exam_dates[student_id].sort()  # Keep sorted for gap checking
            
            # Allocate rooms
            unaccommodated = allocate_shared_rooms(pair_exams)
            unaccommodated_students.extend(unaccommodated)
            
            # print(f"Scheduled pair {pair} on {best_date} at {start_time}-{end_time}")
    
    return exams_created, unaccommodated_students



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
        return [SLOTS[0], SLOTS[1], SLOTS[2]]  # Morning first, then afternoon, then evening
    elif preference == "evening":
        return [SLOTS[2], SLOTS[1], SLOTS[0]]  # Evening first, then afternoon, then morning
    else:  # mixed
        return [SLOTS[0], SLOTS[1], SLOTS[2]]  # Default order but will be randomized

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

def find_compatible_courses_within_group(courses):
    """
    Find compatible courses within a specific group (courses that don't share students)
    """
    if not courses:
        return []
    
    # Build conflict matrix for these courses
    conflict_matrix = defaultdict(int)
    course_ids = [c.id for c in courses]
    
    # Get all enrollments for these courses grouped by student
    student_courses = defaultdict(list)
    for enrollment in Enrollment.objects.filter(course_id__in=course_ids):
        student_courses[enrollment.student_id].append(enrollment.course_id)
    
    # Build conflict matrix
    for student_id, student_course_ids in student_courses.items():
        for i, course1 in enumerate(student_course_ids):
            for course2 in student_course_ids[i+1:]:
                course_pair = tuple(sorted([course1, course2]))
                conflict_matrix[course_pair] += 1
    
    # Find compatible groups using greedy algorithm
    remaining_courses = set(course_ids)
    course_groups = []
    
    while remaining_courses:
        course_group = []
        
        # Pick a course with the fewest remaining compatible options
        course1 = min(
            remaining_courses,
            key=lambda c: len([rc for rc in remaining_courses if rc != c and 
                              tuple(sorted([c, rc])) not in conflict_matrix])
        )
        
        course_group.append(course1)
        remaining_courses.remove(course1)
        
        # Find courses compatible with all courses in current group
        compatible_with_group = set()
        for candidate in remaining_courses:
            is_compatible = True
            for group_course in course_group:
                pair = tuple(sorted([candidate, group_course]))
                if pair in conflict_matrix and conflict_matrix[pair] > 0:
                    is_compatible = False
                    break
            if is_compatible:
                compatible_with_group.add(candidate)
        
        # Add more courses to the group
        while compatible_with_group and len(course_group) < 8:  # Limit group size
            next_course = min(
                compatible_with_group,
                key=lambda c: len([rc for rc in remaining_courses if rc != c and 
                                  tuple(sorted([c, rc])) not in conflict_matrix])
            )
            
            course_group.append(next_course)
            remaining_courses.remove(next_course)
            
            # Update compatible set
            new_compatible = set()
            for candidate in compatible_with_group:
                if candidate == next_course:
                    continue
                pair = tuple(sorted([candidate, next_course]))
                if pair not in conflict_matrix or conflict_matrix[pair] == 0:
                    new_compatible.add(candidate)
            compatible_with_group = new_compatible & remaining_courses
        
        if course_group:
            course_groups.append(course_group)
    
    return course_groups

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

def can_schedule_course_group_on_slot(course_group, proposed_date, slot_info, student_exam_dates):
    """
    Check if a course group can be scheduled on the proposed date and slot
    """
    conflicts = []
    slot_label, start_time, end_time = slot_info
    
    for course_id in course_group:
        student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
        
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

def get_exam_slots(start_date, max_slots=None):
    """
    Generate a list of available exam slots starting from a given date.
    """
    date_slots = []
    current_date = start_date

    while max_slots is None or len(date_slots) < max_slots:
        weekday = current_date.strftime('%A')
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
                if max_slots and len(date_slots) >= max_slots:
                    break
        current_date += timedelta(days=1)

    return date_slots

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate exam schedule considering course groups and their preferences
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    # Group courses by their preferences
    courses_by_preference = group_courses_by_preference()
    
    # Find compatible groups within each preference category
    all_course_groups = []
    group_preferences = []
    
    for preference, courses in courses_by_preference.items():
        if course_ids:
            # Filter courses if specific course_ids are provided
            courses = [c for c in courses if c.id in course_ids]
        
        compatible_groups = find_compatible_courses_within_group(courses)
        
        for group in compatible_groups:
            all_course_groups.append(group)
            group_preferences.append(preference)
    
    # Generate enough slots
    estimated_slots_needed = len(all_course_groups) * 3
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
    
    # Group slots by date for easier access
    slots_by_date = defaultdict(list)
    for slot_idx, (date, label, start, end) in enumerate(date_slots):
        slots_by_date[date].append((slot_idx, label, start, end))
    
    exams_created = []
    student_exam_dates = defaultdict(list)
    assigned_slots = set()
    
    with transaction.atomic():
        # Sort course groups by difficulty (most constrained first)
        group_difficulties = []
        for i, course_group in enumerate(all_course_groups):
            total_students = sum(
                Enrollment.objects.filter(course_id=course_id).count() 
                for course_id in course_group
            )
            group_difficulties.append((i, total_students, group_preferences[i]))
        
        group_difficulties.sort(key=lambda x: x[1], reverse=True)
        
        # Schedule each course group
        for group_idx, total_students, preference in group_difficulties:
            course_group = all_course_groups[group_idx]
            
            # Get preferred slots for this group
            if preference == "mostly morning":
                preferred_slot_order = [0, 1, 2]  # Morning, Afternoon, Evening
            elif preference == "evening":
                preferred_slot_order = [2, 1, 0]  # Evening, Afternoon, Morning
            else:  # mixed
                preferred_slot_order = [0, 1, 2]
                if random.random() < 0.5:  # Random variation for mixed groups
                    random.shuffle(preferred_slot_order)
            
            scheduled = False
            
            # Try each date
            for date in sorted(slots_by_date.keys()):
                if scheduled:
                    break
                
                available_slots = [
                    (slot_idx, label, start, end) 
                    for slot_idx, label, start, end in slots_by_date[date]
                    if slot_idx not in assigned_slots
                ]
                
                # Sort available slots by preference
                weekday = date.strftime('%A')
                if weekday == 'Friday':
                    # Only morning and afternoon available on Friday
                    available_slots = [s for s in available_slots if s[1] in ['Morning', 'Afternoon']]
                
                # Sort by preference
                slot_priority = {'Morning': 0, 'Afternoon': 1, 'Evening': 2}
                available_slots.sort(key=lambda x: preferred_slot_order.index(slot_priority[x[1]]))
                
                # Try each slot in preference order
                for slot_idx, label, start_time, end_time in available_slots:
                    can_schedule, conflicts = can_schedule_course_group_on_slot(
                        course_group, date, (label, start_time, end_time), student_exam_dates
                    )
                    
                    if can_schedule:
                        # Schedule all courses in this group
                        group_exams = []
                        for course_id in course_group:
                            course = Course.objects.get(id=course_id)
                            
                            exam = Exam.objects.create(
                                course=course,
                                date=date,
                                start_time=start_time,
                                end_time=end_time
                            )
                            exams_created.append(exam)
                            group_exams.append(exam)
                            
                            # Update student exam dates
                            student_ids = Enrollment.objects.filter(course=course).values_list('student_id', flat=True)
                            for student_id in student_ids:
                                student_exam_dates[student_id].append(date)
                                student_exam_dates[student_id].sort()
                        
                        # Mark slot as assigned
                        assigned_slots.add(slot_idx)
                        
                        # Allocate rooms for this group
                        try:
                            unaccommodated = allocate_shared_rooms(group_exams)
                            print(f"Scheduled {preference} group {course_group} on {date} {label} ({start_time}-{end_time})")
                            if unaccommodated:
                                print(f"  Warning: {len(unaccommodated)} students unaccommodated")
                        except Exception as e:
                            print(f"  Room allocation error: {e}")
                        
                        scheduled = True
                        break
            
            if not scheduled:
                print(f"Could not schedule {preference} group {course_group}")
                raise ValueError(f"Cannot find suitable slot for {preference} course group {course_group}")
    
    return exams_created

# Keep the existing room allocation function
def allocate_shared_rooms(exams):
    """
    Allocate rooms for exams scheduled in the same slot
    """
    if not exams:
        return []

    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    # Group students by exam
    students_by_exam = {}
    for exam in exams:
        enrolled_students = list(
            Enrollment.objects.filter(course=exam.course).select_related('student')
        )
        students_by_exam[exam.id] = enrolled_students

    unaccommodated_students = []
    assigned_student_exams = []

    # Simple allocation: try to fit exams in rooms
    room_index = 0
    for exam in exams:
        if room_index >= len(rooms):
            # No more rooms available
            for enrollment in students_by_exam[exam.id]:
                unaccommodated_students.append(enrollment.student)
            continue
        
        room = rooms[room_index]
        students = students_by_exam[exam.id]
        
        # Check if all students fit in this room
        if len(students) <= room.capacity:
            # All students fit
            for enrollment in students:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam, room=room)
                )
            room_index += 1
        else:
            # Need to split or find multiple rooms
            allocated = students[:room.capacity]
            overflow = students[room.capacity:]
            
            for enrollment in allocated:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam, room=room)
                )
            
            # Add overflow to unaccommodated
            for enrollment in overflow:
                unaccommodated_students.append(enrollment.student)
            
            room_index += 1

    # Save all assignments
    StudentExam.objects.bulk_create(assigned_student_exams)
    
    return unaccommodated_students
def verify_day_off_constraints(min_gap_days=2):
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

def allocate_shared_rooms(exams):
    if not exams:
        return []

    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    # Step 1: Group students by exam
    students_by_exam = {}
    for exam in exams:
        enrolled_students = list(
            Enrollment.objects.filter(course=exam.course).select_related('student')
        )
        students_by_exam[exam.id] = enrolled_students

    unaccommodated_students = []

    # Step 2: Prepare exam pairs - pair exams (avoid adjacent semester pairing if needed)
    exam_pairs = []
    used_exams = set()

    for i in range(len(exams)):
        if exams[i].id in used_exams:
            continue
        for j in range(i + 1, len(exams)):
            if exams[j].id in used_exams:
                continue
            if abs(int(exams[i].course.semester.name.split(" ")[1]) - int(exams[j].course.semester.name.split(" ")[1])) > 1:
                exam_pairs.append((exams[i], exams[j]))
                used_exams.update({exams[i].id, exams[j].id})
                break
        else:
            # If no suitable pair, leave it as single
            exam_pairs.append((exams[i], None))
            used_exams.add(exams[i].id)

    room_index = 0
    assigned_student_exams = []

    # Step 3: Allocate rooms per exam pair
    for pair in exam_pairs:
        if room_index >= len(rooms):
            # No rooms left, all students unaccommodated
            if pair[0]:
                unaccommodated_students.extend([s.student for s in students_by_exam[pair[0].id]])
            if pair[1]:
                unaccommodated_students.extend([s.student for s in students_by_exam[pair[1].id]])
            continue

        room = rooms[room_index]
        room_index += 1

        capacity = room.capacity
        cap_per_exam = capacity // 2

        exams_to_allocate = [pair[0]]
        if pair[1]:
            exams_to_allocate.append(pair[1])

        for exam in exams_to_allocate:
            students = students_by_exam.get(exam.id, [])
            allocated = students[:cap_per_exam]
            overflow = students[cap_per_exam:]

            for enrollment in allocated:
                assigned_student_exams.append(StudentExam(student=enrollment.student, exam=exam, room=room))

            students_by_exam[exam.id] = overflow  # leftover students for reallocation

    # Step 4: Allocate overflow students into any remaining rooms (2 exams per room rule)
    remaining_exam_ids = [exam.id for exam in exams if students_by_exam[exam.id]]

    while room_index < len(rooms) and remaining_exam_ids:
        room = rooms[room_index]
        room_index += 1
        cap_per_exam = room.capacity // 2

        # Try to pick two exams with remaining students
        first_exam_id = remaining_exam_ids.pop(0)
        second_exam_id = None

        for i, exam_id in enumerate(remaining_exam_ids):
            if abs(
                int(Exam.objects.get(id=first_exam_id).course.semester.name.split(" ")[1])-
                int(Exam.objects.get(id=exam_id).course.semester.name.split(" ")[1])
            ) >= 2:
                second_exam_id = exam_id
                remaining_exam_ids.pop(i)
                break

        exams_in_room = [first_exam_id] if not second_exam_id else [first_exam_id, second_exam_id]

        for exam_id in exams_in_room:
            exam = Exam.objects.get(id=exam_id)
            students = students_by_exam.get(exam_id, [])
            allocated = students[:cap_per_exam]
            overflow = students[cap_per_exam:]

            for enrollment in allocated:
                assigned_student_exams.append(StudentExam(student=enrollment.student, exam=exam, room=room))

            students_by_exam[exam_id] = overflow
            if overflow:
                remaining_exam_ids.append(exam_id)  # Still has overflow

    # Step 5: Any remaining unaccommodated students
    for exam_id in students_by_exam:
        for enrollment in students_by_exam[exam_id]:
            unaccommodated_students.append(enrollment.student)

    # Step 6: Save allocations
    StudentExam.objects.bulk_create(assigned_student_exams)

    return unaccommodated_students
 

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

def find_optimal_exam_dates(start_date=None):
    """
    Find optimal dates for scheduling exams based on the course enrollment patterns
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    # Get course conflict matrix
    conflict_matrix = analyze_student_course_conflicts()
    
    # Find compatible course pairs
    course_pairs = find_compatible_courses(conflict_matrix)
    
    # Calculate the minimum number of days needed
    min_days_needed = (len(course_pairs) // 3) +((len(course_pairs) // 3)-1) # 3 slots per day
    print("Days: ", min_days_needed)
    if len(course_pairs) % 3 > 0:
        min_days_needed += 1
    
    # Generate enough slots
    date_slots = get_exam_slots(start_date, max_slots=min_days_needed * 3 + 5)  # Add buffer
    
    return {
        'start_date': start_date,
        'suggested_end_date': start_date + timedelta(days=min_days_needed + 2),  # Add buffer
        'min_days_needed': min_days_needed,
        'course_pairs': course_pairs,
        'available_slots': date_slots[:min_days_needed * 3]
    }

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