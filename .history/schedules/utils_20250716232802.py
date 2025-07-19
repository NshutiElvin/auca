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
    """
    Find groups of courses that can be scheduled together (no shared students)
    """
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
            while compatible_with_group and len(course_group) < 10:   
                # Select the course with fewest remaining compatible options
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

def get_course_student_count(course_id):
    """Get the number of students enrolled in a course"""
    return Enrollment.objects.filter(course_id=course_id).count()

def can_fit_courses_in_slot(course_ids, total_room_capacity):
    """Check if courses can fit in available room capacity"""
    total_students = sum(get_course_student_count(course_id) for course_id in course_ids)
    return total_students <= total_room_capacity

def has_student_conflicts(course_ids, date, student_exam_dates):
    """Check if any students have conflicts for the given courses on the given date"""
    for course_id in course_ids:
        student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
        for student_id in student_ids:
            if date in student_exam_dates.get(student_id, []):
                return True
    return False

def are_courses_compatible(course_ids, conflict_matrix):
    """Check if courses are compatible (no shared students)"""
    for i, course1 in enumerate(course_ids):
        for course2 in course_ids[i+1:]:
            pair = tuple(sorted([course1, course2]))
            if pair in conflict_matrix and conflict_matrix[pair] > 0:
                return False
    return True

def get_preference_priority(course_id, slot_label):
    """Get priority score for a course in a specific slot (lower is better)"""
    course = Course.objects.get(id=course_id)
    group = get_course_group(course)
    preference = GROUP_PREFERENCES.get(group, "mixed")
    
    slot_priority = {'Morning': 0, 'Afternoon': 1, 'Evening': 2}
    slot_index = slot_priority.get(slot_label, 1)
    
    if preference == "mostly morning":
        return slot_index
    elif preference == "evening":
        return 2 - slot_index
    else:  # mixed
        return abs(slot_index - 1)  # Prefer afternoon, then morning/evening

def maximize_exams_per_slot(unscheduled_courses, date, slot_label, start_time, end_time, 
                           student_exam_dates, conflict_matrix, total_room_capacity):
    """
    Maximize the number of exams that can be scheduled in a single slot
    Returns the best combination of courses for this slot
    """
    if not unscheduled_courses:
        return []
    
    # Filter courses that can potentially fit in this slot
    # (no student conflicts and within room capacity individually)
    eligible_courses = []
    for course_id in unscheduled_courses:
        # Check student conflicts
        if has_student_conflicts([course_id], date, student_exam_dates):
            continue
        
        # Check room capacity (individual course)
        student_count = get_course_student_count(course_id)
        if student_count > total_room_capacity:
            continue
        
        eligible_courses.append(course_id)
    
    if not eligible_courses:
        return []
    
    # Sort by preference for this slot and student count
    eligible_courses.sort(key=lambda c: (
        get_preference_priority(c, slot_label),
        -get_course_student_count(c)  # Larger courses first
    ))
    
    # Use greedy approach to find the best combination
    best_combination = []
    remaining_capacity = total_room_capacity
    
    for course_id in eligible_courses:
        # Check if this course is compatible with already selected courses
        test_combination = best_combination + [course_id]
        
        if not are_courses_compatible(test_combination, conflict_matrix):
            continue
        
        # Check if it fits in remaining capacity
        course_students = get_course_student_count(course_id)
        if course_students <= remaining_capacity:
            best_combination.append(course_id)
            remaining_capacity -= course_students
    
    return best_combination

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate exam schedule that maximizes the number of exams per slot
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    # Get course conflict matrix
    conflict_matrix = analyze_student_course_conflicts()
    
    # Get all courses that need to be scheduled
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count('enrollments')
    ).filter(enrollment_count__gt=0)
    
    if course_ids:
        enrolled_courses = enrolled_courses.filter(id__in=course_ids)
    
    unscheduled_courses = list(enrolled_courses.values_list('id', flat=True))
    
    # Get total room capacity
    total_room_capacity = get_total_room_capacity()
    
    if total_room_capacity == 0:
        raise ValueError("No rooms available for scheduling")
    
    # Generate enough slots
    estimated_slots_needed = len(unscheduled_courses) * 2  # Conservative estimate
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
    
    exams_created = []
    student_exam_dates = defaultdict(list)
    
    print(f"Starting scheduling for {len(unscheduled_courses)} courses")
    print(f"Total room capacity: {total_room_capacity}")
    
    with transaction.atomic():
        # Schedule exams slot by slot
        for slot_idx, (date, slot_label, start_time, end_time) in enumerate(date_slots):
            if not unscheduled_courses:
                break
            
            print(f"\n=== Scheduling {date} {slot_label} ({start_time}-{end_time}) ===")
            print(f"Remaining courses: {len(unscheduled_courses)}")
            
            # Find the best combination of courses for this slot
            selected_courses = maximize_exams_per_slot(
                unscheduled_courses, date, slot_label, start_time, end_time,
                student_exam_dates, conflict_matrix, total_room_capacity
            )
            
            if not selected_courses:
                print("No courses can be scheduled in this slot")
                continue
            
            # Create exams for selected courses
            slot_exams = []
            total_students_in_slot = 0
            
            for course_id in selected_courses:
                course = Course.objects.get(id=course_id)
                student_count = get_course_student_count(course_id)
                
                exam = Exam.objects.create(
                    course=course,
                    date=date,
                    start_time=start_time,
                    end_time=end_time
                )
                
                slot_exams.append(exam)
                exams_created.append(exam)
                total_students_in_slot += student_count
                
                # Update student exam dates
                student_ids = Enrollment.objects.filter(course=course).values_list('student_id', flat=True)
                for student_id in student_ids:
                    student_exam_dates[student_id].append(date)
                    student_exam_dates[student_id].sort()
                
                # Remove from unscheduled
                unscheduled_courses.remove(course_id)
                
                print(f"  + {course.title} ({student_count} students)")
            
            print(f"  Total students in slot: {total_students_in_slot}/{total_room_capacity}")
            print(f"  Capacity utilization: {(total_students_in_slot/total_room_capacity)*100:.1f}%")
            
            # Allocate rooms for this slot
            try:
                unaccommodated = allocate_shared_rooms(slot_exams)
                if unaccommodated:
                    print(f"  Warning: {len(unaccommodated)} students unaccommodated")
            except Exception as e:
                print(f"  Room allocation error: {e}")
    
    print(f"\n=== Scheduling Complete ===")
    print(f"Total exams created: {len(exams_created)}")
    print(f"Unscheduled courses: {len(unscheduled_courses)}")
    
    if unscheduled_courses:
        print("Unscheduled courses:")
        for course_id in unscheduled_courses:
            course = Course.objects.get(id=course_id)
            student_count = get_course_student_count(course_id)
            print(f"  - {course.name} ({student_count} students)")
    
    return exams_created, unscheduled_courses

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

    # Advanced allocation: try to pair compatible exams in rooms
    exam_pairs = []
    used_exams = set()

    # First, try to pair exams from different semesters
    for i in range(len(exams)):
        if exams[i].id in used_exams:
            continue
        for j in range(i + 1, len(exams)):
            if exams[j].id in used_exams:
                continue
            # Check if semesters are compatible (differ by more than 1)
            if hasattr(exams[i].course, 'semester') and hasattr(exams[j].course, 'semester'):
                try:
                    sem1 = int(exams[i].course.semester.name.split(" ")[1])
                    sem2 = int(exams[j].course.semester.name.split(" ")[1])
                    if abs(sem1 - sem2) > 1:
                        exam_pairs.append((exams[i], exams[j]))
                        used_exams.update({exams[i].id, exams[j].id})
                        break
                except (AttributeError, ValueError, IndexError):
                    # If semester parsing fails, treat as compatible
                    exam_pairs.append((exams[i], exams[j]))
                    used_exams.update({exams[i].id, exams[j].id})
                    break
        else:
            # If no suitable pair found, schedule alone
            exam_pairs.append((exams[i], None))
            used_exams.add(exams[i].id)

    room_index = 0

    # Allocate rooms for exam pairs
    for pair in exam_pairs:
        if room_index >= len(rooms):
            # No more rooms available
            for exam in pair:
                if exam:
                    unaccommodated_students.extend([s.student for s in students_by_exam[exam.id]])
            continue

        room = rooms[room_index]
        room_index += 1

        if pair[1] is None:
            # Single exam in room
            exam = pair[0]
            students = students_by_exam[exam.id]
            
            if len(students) <= room.capacity:
                # All students fit
                for enrollment in students:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam, room=room)
                    )
            else:
                # Partial accommodation
                accommodated = students[:room.capacity]
                overflow = students[room.capacity:]
                
                for enrollment in accommodated:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam, room=room)
                    )
                
                for enrollment in overflow:
                    unaccommodated_students.append(enrollment.student)
        else:
            # Two exams in room
            exam1, exam2 = pair
            students1 = students_by_exam[exam1.id]
            students2 = students_by_exam[exam2.id]
            
            capacity_per_exam = room.capacity // 2
            
            # Allocate first exam
            if len(students1) <= capacity_per_exam:
                for enrollment in students1:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam1, room=room)
                    )
            else:
                accommodated = students1[:capacity_per_exam]
                overflow = students1[capacity_per_exam:]
                
                for enrollment in accommodated:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam1, room=room)
                    )
                
                for enrollment in overflow:
                    unaccommodated_students.append(enrollment.student)
            
            # Allocate second exam
            if len(students2) <= capacity_per_exam:
                for enrollment in students2:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam2, room=room)
                    )
            else:
                accommodated = students2[:capacity_per_exam]
                overflow = students2[capacity_per_exam:]
                
                for enrollment in accommodated:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam2, room=room)
                    )
                
                for enrollment in overflow:
                    unaccommodated_students.append(enrollment.student)

    # Save all assignments
    StudentExam.objects.bulk_create(assigned_student_exams)
    
    return unaccommodated_students

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
    """
    with transaction.atomic():
        exam = Exam.objects.get(id=exam_id)
        
        # Store original values for rollback if needed
        original_date = exam.date
        original_start_time = exam.start_time
        original_end_time = exam.end_time
        
        # Validate day of week
        weekday = new_date.strftime('%A')
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")
        
        # Validate and set time slot
        new_start_time = exam.start_time
        new_end_time = exam.end_time
        
        if slot:
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
        
        # Check student conflicts
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
        
        # Check room capacity
        exam_student_count = Enrollment.objects.filter(course=exam.course).count()
        existing_slot_exams = Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ).exclude(id=exam_id)
        
        total_students_needed = exam_student_count
        for other_exam in existing_slot_exams:
            other_exam_students = Enrollment.objects.filter(course=other_exam.course).count()
            total_students_needed += other_exam_students
        
        total_room_capacity = get_total_room_capacity()
        if total_students_needed > total_room_capacity:
            raise ValueError(
                f"Insufficient room capacity. Required: {total_students_needed} students, "
                f"Available: {total_room_capacity} seats."
            )
        
        # Update exam
        exam.date = new_date
        exam.start_time = new_start_time
        exam.end_time = new_end_time
        exam.save()
        
        # Reallocate rooms for this time slot
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
                    f"Room allocation failed: {len(unaccommodated)} students could not be accommodated."
                )
        except Exception as e:
            # Rollback on any room allocation error
            exam.date = original_date
            exam.start_time = original_start_time
            exam.end_time = original_end_time
            exam.save()
            raise ValueError(f"Room allocation error: {str(e)}")
    
    return exam

def get_unaccommodated_students():
    """
    Get a list of students who couldn't be accommodated in the exam schedule
    """
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
    
    return conflicts