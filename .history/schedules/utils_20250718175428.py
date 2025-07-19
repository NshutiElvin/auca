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
            while compatible_with_group:  # Limit to 10 courses per group for practical reasons
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


def find_compatible_courses_within_group(courses):
    """
    Efficiently groups courses without conflicts for large datasets.
    Returns list of conflict-free course groups.
    """
    if not courses:
        return []

    # Step 1: Build conflict graph using streaming approach
    conflict_graph = defaultdict(set)
    student_courses = defaultdict(list)
    
    # Use iterator to minimize memory (important for large datasets)
    enrollment_iter = Enrollment.objects.filter(course_id__in=courses).iterator()
    
    for enrollment in enrollment_iter:
        course_key = (enrollment.course_id, enrollment.group_id)
        student_courses[enrollment.student_id].append(course_key)

    # Process students in batches if needed
    for student_id, courses_list in student_courses.items():
        # Add conflicts for all pairs of courses taken by this student
        for i in range(len(courses_list)):
            for j in range(i + 1, len(courses_list)):
                course1, course2 = courses_list[i], courses_list[j]
                conflict_graph[course1].add(course2)
                conflict_graph[course2].add(course1)

    # Step 2: Greedy coloring with optimizations for large graphs
    color_assignment = {}
    groups = []
    
    # Process courses by degree (number of conflicts) in descending order
    course_queue = [(-len(conflicts), course) for course, conflicts in conflict_graph.items()]
    heapq.heapify(course_queue)
    
    # Track available colors for each course
    color_availability = defaultdict(set)
    
    while course_queue:
        _, course = heapq.heappop(course_queue)
        
        # Find the first available color not used by neighbors
        used_colors = {color_assignment[n] for n in conflict_graph[course] 
                      if n in color_assignment}
        
        # Find the smallest available color
        for color in range(len(groups) + 1):
            if color not in used_colors:
                if color == len(groups):
                    groups.append([])
                color_assignment[course] = color
                groups[color].append(course)
                break

    # Add courses without any conflicts (not in conflict_graph)
    all_courses = {(e.course_id, e.group_id) for e in Enrollment.objects.filter(
        course_id__in=courses).only('course_id', 'group_id')}
    conflict_free_courses = all_courses - set(conflict_graph.keys())
    
    if conflict_free_courses:
        # Add all conflict-free courses to the first group
        if groups:
            groups[0].extend(conflict_free_courses)
        else:
            groups.append(list(conflict_free_courses))

    return groups

# def find_compatible_courses_within_group(courses):
#     """
#     Find compatible courses within a specific group (courses that don't share students)
#     """
#     if not courses:
#         return []
    
#     # Build conflict matrix for these courses
#     conflict_matrix = defaultdict(int)
#     course_ids = courses
    
#     all_courses= set()
#     # Get all enrollments for these courses grouped by student
#     student_courses = defaultdict(list)
#     for enrollment in Enrollment.objects.filter(course_id__in=course_ids):
        
#         student_course=(enrollment.course_id, enrollment.group_id)
#         student_courses[enrollment.student_id].append(student_course)
#         all_courses.add(student_course)
    
#     # Build conflict matrix
#     for student_id, student_course_ids in student_courses.items():
#         for i, course1 in enumerate(student_course_ids):
#             for course2 in student_course_ids[i+1:]:
#                 course_pair = tuple(sorted([course1, course2]))
#                 conflict_matrix[course_pair] += 1
    
#     # Find compatible groups using greedy algorithm
#     remaining_courses = all_courses
#     course_groups = []
    
#     while remaining_courses:
#         course_group = []
        
#         # Pick a course with the fewest remaining compatible options
#         course1 = max(
#             remaining_courses,
#             key=lambda c: len([rc for rc in remaining_courses if rc != c and 
#                               tuple(sorted([c, rc])) not in conflict_matrix])
#         )
        
#         course_group.append(course1)
#         remaining_courses.remove(course1)
        
#         # Find courses compatible with all courses in current group
#         compatible_with_group = set()
#         for candidate in remaining_courses:
#             is_compatible = True
#             for group_course in course_group:
#                 pair = tuple(sorted([candidate, group_course]))
#                 if pair in conflict_matrix and conflict_matrix[pair] > 0:
#                     is_compatible = False
#                     break
#             if is_compatible:
#                 compatible_with_group.add(candidate)
        
#         # Add more courses to the group
#         while compatible_with_group:  # Limit group size
#             next_course = max(
#                 compatible_with_group,
#                 key=lambda c: len([rc for rc in remaining_courses if rc != c and 
#                                   tuple(sorted([c, rc])) not in conflict_matrix])
#             )
            
#             course_group.append(next_course)
#             remaining_courses.remove(next_course)
            
#             # Update compatible set
#             new_compatible = set()
#             for candidate in compatible_with_group:
#                 if candidate == next_course:
#                     continue
#                 pair = tuple(sorted([candidate, next_course]))
#                 if pair not in conflict_matrix or conflict_matrix[pair] == 0:
#                     new_compatible.add(candidate)
#             compatible_with_group = new_compatible & remaining_courses
        
#         if course_group:
#             course_groups.append(course_group)
    
#     return course_groups

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


def generate_exam_schedule(start_date=None, end_date=None,course_ids=None, semester=None):
 
    try:
        
        if not start_date:
            start_date = now().date() + timedelta(days=1)
            logger.debug(f"Using default start date: {start_date}")
        
        # Get enrolled courses
        if course_ids:
            logger.info(f"Filtering courses for specific IDs: {course_ids}")
            enrolled_courses = course_ids
        else:
            logger.debug("Fetching all enrolled courses")
            enrolled_courses = Course.objects.annotate(
                enrollment_count=Count('enrollments')
            ).filter(enrollment_count__gt=0)
        
        logger.info(f"Found {len(enrolled_courses)} enrolled courses to schedule")
        
        # Find compatible course groups
        compatible_groups = find_compatible_courses_within_group(enrolled_courses)
        print(compatible_groups)
        
        if not compatible_groups:
            logger.warning("No compatible course groups found")
            return [], "No compatible course groups found"
        
        logger.info(f"Found {len(compatible_groups)} compatible course groups")
        
        # Generate exam slots
        estimated_slots_needed = len(compatible_groups) * 6
        logger.debug(f"Estimating {estimated_slots_needed} exam slots needed")
        
        date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
        slots_by_date = defaultdict(list)
        
        for slot_idx, (date, label, start, end) in enumerate(date_slots):
            slots_by_date[date].append((slot_idx, label, start, end))
        
        logger.info(f"Generated {len(date_slots)} exam slots across {len(slots_by_date)} dates")
        
        exams_created = []
        student_exam_dates = defaultdict(list)
        scheduled_groups = set()
        
        with transaction.atomic():
            logger.info("Beginning transaction for exam scheduling")
            dates = sorted(slots_by_date.keys())
            logger.debug(f"Processing dates in order: {dates}")
            
            for step, date in enumerate(dates):
                weekday = date.strftime('%A')
                logger.debug(f"Processing date {date} ({weekday}), step {step}")
                
                if weekday == "Saturday":
                    logger.debug("Skipping Saturday")
                    continue
                
                # Try each unscheduled group
                for group_idx, course_group in enumerate(compatible_groups):
                    if group_idx in scheduled_groups:
                        continue
                    
                    logger.debug(f"Attempting to schedule group {group_idx} on {date}")
                    group_exams = []
                    scheduled_this_group = True
                    
                    for group_course in course_group:

                        course_id= group_course[0]
                        group= group_course[1]
                        group= CourseGroup.objects.get(id= group)
                        try:
                            
                            course = Course.objects.get(id=course_id)
                            logger.debug(f"Processing course {course.id}: {course.title}")
                        except Course.DoesNotExist:
                            logger.error(f"Course {course_id} not found - skipping group")
                            scheduled_this_group = False
                            break
                        
                        
                        logger.debug(f"Course preference group: {group.group_name}")
                        
                        # Check scheduling conflicts
                        can_schedule, conflicts = can_schedule_course_group_on_slot(
                            group,course, date, student_exam_dates
                        )
                        if not can_schedule:
                            logger.warning(
                                f"Cannot schedule course {course.id} due to conflicts: {conflicts}"
                            )
                            scheduled_this_group = False
                            break
                        
                        # Determine time slot based on preference
                        if group.group_name in ["A", "B"]:
                            start_time = time(8, 0)
                            end_time = time(11, 0)
                            slot = "Morning"
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
                            logger.warning(f"Unknown preference group {group.group_name} - using default")
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
                            group_exams.append(exam)
                            logger.info(
                                f"Created exam for course {course.id} on {date} "
                                f"at {start_time}-{end_time} ({slot})"
                            )
                            
                            # Attempt to reschedule to earlier date if possible
                            if len(dates[:step+1]) > 1:
                                for innerdate in dates[:step]:
                                    can_reschedule, conflicts = can_schedule_course_group_on_slot(
                                        exam.group,course, innerdate, student_exam_dates
                                    )
                                    if can_reschedule:
                                        logger.debug(
                                            f"Rescheduling exam {exam.id} from {exam.date} to {innerdate}"
                                        )
                                        exam.date = innerdate
                                        exam.save()
                                    else:
                                        logger.debug(
                                            f"Cannot reschedule to {innerdate} due to: {conflicts}"
                                        )
                            
                            # Update student exam dates
                            student_ids = Enrollment.objects.filter(
                                course=course, group=group
                            ).values_list('student_id', flat=True)
                            for student_id in student_ids:
                                student_exam_dates[student_id].append(date)
                            
                        except Exception as e:
                            logger.error(f"Failed to create exam for course {course.id}: {str(e)}")
                            scheduled_this_group = False
                            break
                    
                    if scheduled_this_group and group_exams:
                        scheduled_groups.add(group_idx)
                        try:
                            unaccommodated = allocate_shared_rooms(group_exams)
                            logger.info(
                                f"Successfully scheduled group {group_idx} on {date} "
                                f"with {len(group_exams)} exams"
                            )
                        except Exception as e:
                            logger.error(
                                f"Room allocation error for group {group_idx}: {str(e)}"
                            )
            
            logger.info(f"Successfully scheduled {len(scheduled_groups)}/{len(compatible_groups)} groups")
        
        logger.info(f"Exam schedule generation completed. Created {len(exams_created)} exams")
        return exams_created, None
    
    except Exception as e:
        logger.error(f"Failed to generate exam schedule: {str(e)}", exc_info=True)
        return [], f"Error generating schedule: {str(e)}"
 
 
 
 
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
            Enrollment.objects.filter(group=exam.group).select_related('student')
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
            if abs(int(exams[i].group.course.semester.name.split(" ")[1]) - int(exams[j].group.course.semester.name.split(" ")[1])) > 1:
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
                int(Exam.objects.get(id=first_exam_id).group.course.semester.name.split(" ")[1])-
                int(Exam.objects.get(id=exam_id).group.course.semester.name.split(" ")[1])
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
    date_slots = get_exam_slots(start_date, max_slots=min_days_needed )  # Add buffer
    
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


