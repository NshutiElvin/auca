from datetime import timedelta, time
from collections import defaultdict
import random
from django.db import transaction
from django.utils.timezone import now
from django.db.models import Sum, Count

from courses.models import Course
from exams.models import Exam, StudentExam
from enrollments.models import Enrollment
from rooms.models import Room
from pprint import pprint

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
    """Get preferred slots for a course group based on GROUP_PREFERENCES"""
    preference = GROUP_PREFERENCES.get(group_name, "mixed")
    
    if preference == "mostly morning":
        return [SLOTS[0], SLOTS[1], SLOTS[2]]   
    elif preference == "evening":
        return [SLOTS[2], SLOTS[1], SLOTS[0]]   
    else:  
        return [SLOTS[0], SLOTS[1], SLOTS[2]]  

def get_course_group(course):
    """Extract the group from course name"""
    if hasattr(course, 'group'):
        return course.group
    
    course_name = course.name or course.title
    if course_name:
        group_char = course_name.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char
    
    if hasattr(course, 'code') and course.code:
        group_char = course.code.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char
    
    return "C"

def analyze_student_course_conflicts():
    """Analyze which courses have students in common"""
    conflict_matrix = defaultdict(int)
    
    student_courses = defaultdict(list)
    for enrollment in Enrollment.objects.all():
        student_courses[enrollment.student_id].append(enrollment.course_id)
    
    for student_id, courses in student_courses.items():
        for i, course1 in enumerate(courses):
            for course2 in courses[i+1:]:
                course_pair = tuple(sorted([course1, course2]))
                conflict_matrix[course_pair] += 1
    
    return conflict_matrix

def find_all_compatible_course_groups():
    """
    Find ALL compatible course groups to maximize room utilization
    Compatible courses = courses that share NO students
    """
    # Get all courses with enrollments
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count('enrollments')
    ).filter(enrollment_count__gt=0)
    
    # Get conflict matrix
    conflict_matrix = analyze_student_course_conflicts()
    
    # Build compatibility graph
    course_ids = list(enrolled_courses.values_list('id', flat=True))
    compatibility_graph = {course_id: set() for course_id in course_ids}
    
    for course1 in course_ids:
        for course2 in course_ids:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if pair not in conflict_matrix or conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    # Find maximum compatible groups using improved algorithm
    remaining_courses = set(course_ids)
    course_groups = []
    
    while remaining_courses:
        # Start with course that has most connections (most flexible)
        start_course = max(
            remaining_courses,
            key=lambda c: len(compatibility_graph[c] & remaining_courses)
        )
        
        current_group = [start_course]
        remaining_courses.remove(start_course)
        
        # Find all courses compatible with ALL courses in current group
        compatible_candidates = set(compatibility_graph[start_course]) & remaining_courses
        
        # Keep adding courses to maximize group size
        while compatible_candidates:
            # Pick course with fewest remaining options (harder to place later)
            next_course = min(
                compatible_candidates,
                key=lambda c: len(compatibility_graph[c] & remaining_courses)
            )
            
            current_group.append(next_course)
            remaining_courses.remove(next_course)
            
            # Update candidates - must be compatible with ALL courses in group
            new_compatible = set()
            for candidate in compatible_candidates:
                if candidate == next_course:
                    continue
                if candidate in compatibility_graph[next_course]:
                    new_compatible.add(candidate)
            
            compatible_candidates = new_compatible & remaining_courses
        
        course_groups.append(current_group)
    
    return course_groups

def group_courses_by_time_preference(compatible_groups):
    """Group compatible courses by their time preferences"""
    preference_groups = {
        "mostly morning": [],
        "evening": [],
        "mixed": []
    }
    
    for group in compatible_groups:
        # Determine group preference based on majority
        preferences = []
        for course_id in group:
            course = Course.objects.get(id=course_id)
            group_char = get_course_group(course)
            preference = GROUP_PREFERENCES.get(group_char, "mixed")
            preferences.append(preference)
        
        # Use majority preference
        preference_count = {
            "mostly morning": preferences.count("mostly morning"),
            "evening": preferences.count("evening"),
            "mixed": preferences.count("mixed")
        }
        
        majority_preference = max(preference_count, key=preference_count.get)
        preference_groups[majority_preference].append(group)
    
    return preference_groups

def get_exam_slots(start_date, max_slots=None):
    """Generate available exam slots starting from a given date"""
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

def can_pair_courses_in_room(course1_id, course2_id):
    """
    Check if two courses can be paired in the same room
    They must be from different semesters with at least 1 semester gap
    """
    try:
        course1 = Course.objects.get(id=course1_id)
        course2 = Course.objects.get(id=course2_id)
        
        # Extract semester numbers
        semester1 = int(course1.semester.name.split(" ")[1])
        semester2 = int(course2.semester.name.split(" ")[1])
        
        # Must have at least 1 semester gap
        return abs(semester1 - semester2) >= 1
    except:
        return False

def create_room_allocation_pairs(course_group):
    """
    Create optimal pairs of courses for room allocation
    Prioritize pairing courses from different semesters
    """
    unpaired_courses = list(course_group)
    course_pairs = []
    
    # First pass: pair courses with semester constraints
    i = 0
    while i < len(unpaired_courses):
        course1 = unpaired_courses[i]
        paired = False
        
        # Look for a compatible course to pair with
        for j in range(i + 1, len(unpaired_courses)):
            course2 = unpaired_courses[j]
            if can_pair_courses_in_room(course1, course2):
                course_pairs.append((course1, course2))
                unpaired_courses.remove(course1)
                unpaired_courses.remove(course2)
                paired = True
                break
        
        if not paired:
            i += 1
    
    # Second pass: add remaining unpaired courses as singles
    for course in unpaired_courses:
        course_pairs.append((course, None))
    
    return course_pairs

def allocate_rooms_optimally(course_pairs, rooms):
    """
    Allocate rooms optimally for course pairs
    Each room hosts max 2 courses, with half capacity for each if paired
    """
    assignments = []
    room_index = 0
    
    # Sort rooms by capacity (largest first)
    sorted_rooms = sorted(rooms, key=lambda r: r.capacity, reverse=True)
    
    for pair in course_pairs:
        if room_index >= len(sorted_rooms):
            # No more rooms available
            break
            
        room = sorted_rooms[room_index]
        
        if pair[1] is None:
            # Single course - gets full room capacity
            course_id = pair[0]
            student_count = Enrollment.objects.filter(course_id=course_id).count()
            
            if student_count <= room.capacity:
                assignments.append({
                    'room': room,
                    'courses': [course_id],
                    'allocations': {course_id: min(student_count, room.capacity)}
                })
                room_index += 1
            else:
                # Course needs multiple rooms
                remaining_students = student_count
                course_assignments = []
                
                while remaining_students > 0 and room_index < len(sorted_rooms):
                    current_room = sorted_rooms[room_index]
                    allocated = min(remaining_students, current_room.capacity)
                    
                    assignments.append({
                        'room': current_room,
                        'courses': [course_id],
                        'allocations': {course_id: allocated}
                    })
                    
                    remaining_students -= allocated
                    room_index += 1
        else:
            # Paired courses - each gets half room capacity
            course1, course2 = pair
            capacity_per_course = room.capacity // 2
            
            course1_students = Enrollment.objects.filter(course_id=course1).count()
            course2_students = Enrollment.objects.filter(course_id=course2).count()
            
            # Allocate what fits in this room
            course1_allocated = min(course1_students, capacity_per_course)
            course2_allocated = min(course2_students, capacity_per_course)
            
            assignments.append({
                'room': room,
                'courses': [course1, course2],
                'allocations': {
                    course1: course1_allocated,
                    course2: course2_allocated
                }
            })
            
            room_index += 1
            
            # Handle overflow students
            course1_overflow = course1_students - course1_allocated
            course2_overflow = course2_students - course2_allocated
            
            # Allocate overflow to additional rooms
            for overflow_course, overflow_count in [(course1, course1_overflow), (course2, course2_overflow)]:
                remaining = overflow_count
                while remaining > 0 and room_index < len(sorted_rooms):
                    overflow_room = sorted_rooms[room_index]
                    allocated = min(remaining, overflow_room.capacity)
                    
                    assignments.append({
                        'room': overflow_room,
                        'courses': [overflow_course],
                        'allocations': {overflow_course: allocated}
                    })
                    
                    remaining -= allocated
                    room_index += 1
    
    return assignments

def create_student_exam_assignments(exam_assignments):
    """
    Create StudentExam objects based on room assignments
    """
    student_exam_objects = []
    
    for assignment in exam_assignments:
        room = assignment['room']
        
        for course_id, student_count in assignment['allocations'].items():
            # Get exam for this course
            exam = Exam.objects.get(course_id=course_id)
            
            # Get students for this course (shuffle to avoid friends sitting together)
            enrollments = list(Enrollment.objects.filter(course_id=course_id).select_related('student'))
            random.shuffle(enrollments)
            
            # Take only the allocated number of students
            allocated_enrollments = enrollments[:student_count]
            
            # Create StudentExam objects
            for enrollment in allocated_enrollments:
                student_exam_objects.append(
                    StudentExam(
                        student=enrollment.student,
                        exam=exam,
                        room=room
                    )
                )
    
    return student_exam_objects

def generate_exam_schedule(start_date=None, course_ids=None):
    """
    Generate optimized exam schedule that maximizes room utilization
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    print("Finding compatible course groups...")
    compatible_groups = find_all_compatible_course_groups()
    
    if course_ids:
        # Filter groups to only include specified courses
        filtered_groups = []
        for group in compatible_groups:
            filtered_group = [c for c in group if c in course_ids]
            if filtered_group:
                filtered_groups.append(filtered_group)
        compatible_groups = filtered_groups
    
    print(f"Found {len(compatible_groups)} compatible course groups")
    for i, group in enumerate(compatible_groups):
        print(f"Group {i+1}: {len(group)} courses")
    
    # Group by time preferences
    preference_groups = group_courses_by_time_preference(compatible_groups)
    
    # Calculate total slots needed
    total_groups = sum(len(groups) for groups in preference_groups.values())
    estimated_slots = total_groups + 5  # Add buffer
    
    print(f"Total course groups: {total_groups}")
    print(f"Estimated slots needed: {estimated_slots}")
    
    # Generate exam slots
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots)
    
    # Get available rooms
    rooms = list(Room.objects.order_by('-capacity'))
    total_room_capacity = sum(r.capacity for r in rooms)
    
    print(f"Available rooms: {len(rooms)}")
    print(f"Total room capacity: {total_room_capacity}")
    
    exams_created = []
    student_exam_dates = defaultdict(list)
    assigned_slots = set()
    
    with transaction.atomic():
        slot_index = 0
        
        # Schedule by preference (morning groups first, then evening, then mixed)
        for preference in ["mostly morning", "evening", "mixed"]:
            groups = preference_groups[preference]
            
            # Sort groups by size (larger groups first - harder to place)
            groups.sort(key=len, reverse=True)
            
            for group in groups:
                if slot_index >= len(date_slots):
                    raise ValueError("Not enough slots available for all course groups")
                
                date, slot_label, start_time, end_time = date_slots[slot_index]
                
                # Check if this slot works with time preference
                if not is_slot_compatible_with_preference(slot_label, preference):
                    # Find next compatible slot
                    found_slot = False
                    for next_slot_index in range(slot_index + 1, len(date_slots)):
                        next_date, next_label, next_start, next_end = date_slots[next_slot_index]
                        if (next_slot_index not in assigned_slots and 
                            is_slot_compatible_with_preference(next_label, preference)):
                            
                            slot_index = next_slot_index
                            date, slot_label, start_time, end_time = next_date, next_label, next_start, next_end
                            found_slot = True
                            break
                    
                    if not found_slot:
                        # Use next available slot regardless of preference
                        slot_index += 1
                        if slot_index >= len(date_slots):
                            raise ValueError("Not enough slots available")
                        date, slot_label, start_time, end_time = date_slots[slot_index]
                
                # Validate student conflicts
                if not validate_student_conflicts(group, date, student_exam_dates):
                    raise ValueError(f"Student conflicts found for group {group} on {date}")
                
                # Create exams for this group
                group_exams = []
                for course_id in group:
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
                
                # Allocate rooms optimally
                course_pairs = create_room_allocation_pairs(group)
                room_assignments = allocate_rooms_optimally(course_pairs, rooms)
                
                # Create student-exam-room assignments
                student_exam_objects = create_student_exam_assignments(room_assignments)
                StudentExam.objects.bulk_create(student_exam_objects)
                
                # Calculate statistics
                total_students = sum(Enrollment.objects.filter(course_id=cid).count() for cid in group)
                accommodated_students = len(student_exam_objects)
                rooms_used = len(set(assignment['room'].id for assignment in room_assignments))
                
                print(f"Scheduled group {group} on {date} {slot_label}")
                print(f"  Courses: {len(group)}")
                print(f"  Students: {accommodated_students}/{total_students} accommodated")
                print(f"  Rooms used: {rooms_used}")
                
                assigned_slots.add(slot_index)
                slot_index += 1
    
    # Generate summary report
    summary = generate_schedule_summary(exams_created)
    
    return exams_created, summary

def is_slot_compatible_with_preference(slot_label, preference):
    """Check if a slot is compatible with time preference"""
    if preference == "mostly morning":
        return slot_label in ["Morning", "Afternoon"]
    elif preference == "evening":
        return slot_label in ["Evening", "Afternoon"]
    else:  # mixed
        return True

def validate_student_conflicts(course_group, proposed_date, student_exam_dates):
    """Validate that no student has conflicts on the proposed date"""
    for course_id in course_group:
        student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
        for student_id in student_ids:
            if proposed_date in student_exam_dates.get(student_id, []):
                return False
    return True

def generate_schedule_summary(exams_created):
    """Generate a summary of the created schedule"""
    summary = {
        'total_exams': len(exams_created),
        'dates_used': len(set(exam.date for exam in exams_created)),
        'rooms_used': len(set(
            se.room.id for se in StudentExam.objects.filter(exam__in=exams_created) if se.room
        )),
        'total_students_scheduled': StudentExam.objects.filter(exam__in=exams_created).count(),
        'unaccommodated_students': StudentExam.objects.filter(
            exam__in=exams_created, room__isnull=True
        ).count()
    }
    
    # Room utilization statistics
    room_usage = defaultdict(int)
    for se in StudentExam.objects.filter(exam__in=exams_created).select_related('room'):
        if se.room:
            room_usage[se.room.id] += 1
    
    summary['room_utilization'] = {
        room_id: {
            'students': count,
            'capacity': Room.objects.get(id=room_id).capacity,
            'utilization_rate': (count / Room.objects.get(id=room_id).capacity) * 100
        }
        for room_id, count in room_usage.items()
    }
    
    return summary

def get_unaccommodated_students():
    """Get students who couldn't be accommodated"""
    unaccommodated = StudentExam.objects.filter(room__isnull=True).select_related('student', 'exam__course')
    
    result = []
    for student_exam in unaccommodated:
        result.append({
            'student': student_exam.student,
            'course': student_exam.exam.course,
            'exam_date': student_exam.exam.date,
            'exam_slot': f"{student_exam.exam.start_time}-{student_exam.exam.end_time}"
        })
    
    return result

def verify_schedule_integrity():
    """Verify that the schedule has no integrity issues"""
    issues = []
    
    # Check for student conflicts
    student_schedules = defaultdict(list)
    for se in StudentExam.objects.select_related('student', 'exam'):
        student_schedules[se.student.id].append(se.exam.date)
    
    for student_id, dates in student_schedules.items():
        if len(dates) != len(set(dates)):
            issues.append(f"Student {student_id} has multiple exams on the same day")
    
    # Check room capacity violations
    room_slots = defaultdict(list)
    for se in StudentExam.objects.select_related('exam', 'room'):
        if se.room:
            slot_key = (se.room.id, se.exam.date, se.exam.start_time)
            room_slots[slot_key].append(se)
    
    for slot_key, assignments in room_slots.items():
        room_id, date, time = slot_key
        room = Room.objects.get(id=room_id)
        if len(assignments) > room.capacity:
            issues.append(f"Room {room_id} overallocated: {len(assignments)} students, capacity {room.capacity}")
    
    return issues

# Keep existing utility functions for compatibility
def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0

def has_sufficient_gap(student_exam_dates, proposed_date, min_gap_days=2):
    """Check if scheduling an exam maintains minimum gap"""
    if not student_exam_dates:
        return True
    
    all_dates = student_exam_dates + [proposed_date]
    all_dates.sort()
    
    for i in range(len(all_dates) - 1):
        gap = (all_dates[i + 1] - all_dates[i]).days
        if gap < min_gap_days:
            return False
    
    return True