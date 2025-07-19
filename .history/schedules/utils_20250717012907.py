from datetime import timedelta, time
from collections import defaultdict
import random
from django.db import transaction
from django.utils.timezone import now
from django.db.models import Sum, Count
from pprint import pprint

from courses.models import Course
from exams.models import Exam, StudentExam
from enrollments.models import Enrollment
from rooms.models import Room

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
    """
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

def find_compatible_courses(conflict_matrix):
    """
    Find groups of compatible courses (no shared students) using a greedy approach
    """
    all_courses = set()
    for course1, course2 in conflict_matrix.keys():
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
                if pair not in conflict_matrix or conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    remaining_courses = set(all_courses)
    course_groups = []
    
    while remaining_courses:
        course_group = []
        course1 = min(
            remaining_courses,
            key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
        )
        course_group.append(course1)
        remaining_courses.remove(course1)
        
        compatible_with_group = set(compatibility_graph[course1]) & remaining_courses
        
        while compatible_with_group:
            next_course = min(
                compatible_with_group,
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
            )
            course_group.append(next_course)
            remaining_courses.remove(next_course)
            compatible_with_group &= set(compatibility_graph[next_course]) & remaining_courses
        
        if course_group:
            course_groups.append(course_group)
    
    return course_groups

def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0

def get_course_group(course):
    """
    Extract the group from course name
    """
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

def are_semesters_compatible(exam1, exam2):
    """Check if two exams have a semester gap of at least 2"""
    if not exam2:
        return True
    return abs(int(exam1.course.semester.name.split(" ")[1]) - 
               int(exam2.course.semester.name.split(" ")[1])) >= 2

def allocate_shared_rooms(exams):
    """
    Allocate rooms for exams, pairing two courses from non-adjacent semesters per room
    """
    if not exams:
        return []

    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    students_by_exam = {}
    for exam in exams:
        enrolled_students = list(
            Enrollment.objects.filter(course=exam.course).select_related('student')
        )
        students_by_exam[exam.id] = enrolled_students

    unaccommodated_students = []
    assigned_student_exams = []
    used_exams = set()

    # Pair exams with non-adjacent semesters
    exam_pairs = []
    for i in range(len(exams)):
        if exams[i].id in used_exams:
            continue
        for j in range(i + 1, len(exams)):
            if exams[j].id in used_exams:
                continue
            if are_semesters_compatible(exams[i], exams[j]):
                exam_pairs.append((exams[i], exams[j]))
                used_exams.update({exams[i].id, exams[j].id})
                break
        else:
            exam_pairs.append((exams[i], None))
            used_exams.add(exams[i].id)

    room_index = 0
    for pair in exam_pairs:
        if room_index >= len(rooms):
            if pair[0]:
                unaccommodated_students.extend([s.student for s in students_by_exam[pair[0].id]])
            if pair[1]:
                unaccommodated_students.extend([s.student for s in students_by_exam[pair[1].id]])
            continue

        room = rooms[room_index]
        room_index += 1
        cap_per_exam = room.capacity // 2 if pair[1] else room.capacity

        exams_to_allocate = [pair[0]]
        if pair[1]:
            exams_to_allocate.append(pair[1])

        for exam in exams_to_allocate:
            students = students_by_exam.get(exam.id, [])
            allocated = students[:cap_per_exam]
            overflow = students[cap_per_exam:]

            for enrollment in allocated:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam, room=room)
                )
            students_by_exam[exam.id] = overflow

    # Allocate overflow students
    remaining_exam_ids = [exam.id for exam in exams if students_by_exam[exam.id]]
    while room_index < len(rooms) and remaining_exam_ids:
        room = rooms[room_index]
        room_index += 1
        cap_per_exam = room.capacity // 2

        first_exam_id = remaining_exam_ids.pop(0)
        second_exam_id = None
        for i, exam_id in enumerate(remaining_exam_ids):
            if are_semesters_compatible(
                Exam.objects.get(id=first_exam_id),
                Exam.objects.get(id=exam_id)
            ):
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
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam, room=room)
                )
            students_by_exam[exam_id] = overflow
            if overflow:
                remaining_exam_ids.append(exam_id)

    for exam_id in students_by_exam:
        for enrollment in students_by_exam[exam_id]:
            unaccommodated_students.append(enrollment.student)

    StudentExam.objects.bulk_create(assigned_student_exams)
    return unaccommodated_students

def get_exam_slots(start_date, max_days=14):
    """
    Generate exam slots for a specified number of days, avoiding NO_EXAM_DAYS
    """
    date_slots = []
    current_date = start_date
    days_added = 0
    
    while days_added < max_days:
        weekday = current_date.strftime('%A')
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
            days_added += 1
        current_date += timedelta(days=1)
    
    return date_slots

def split_course_group(course_group, conflict_matrix):
    """
    Split a course group into smaller compatible subgroups
    """
    compatibility_graph = defaultdict(set)
    for course1 in course_group:
        for course2 in course_group:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if pair not in conflict_matrix or conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    remaining_courses = set(course_group)
    subgroups = []
    
    while remaining_courses:
        subgroup = []
        course1 = min(
            remaining_courses,
            key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
        )
        subgroup.append(course1)
        remaining_courses.remove(course1)
        
        compatible_with_group = set(compatibility_graph[course1]) & remaining_courses
        
        while compatible_with_group:
            next_course = min(
                compatible_with_group,
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
            )
            subgroup.append(next_course)
            remaining_courses.remove(next_course)
            compatible_with_group &= set(compatibility_graph[next_course]) & remaining_courses
        
        if subgroup:
            subgroups.append(subgroup)
    
    return subgroups

def can_schedule_course_group_on_slot(course_group, proposed_date, slot_info, student_exam_dates):
    """
    Check if a course group can be scheduled in a slot
    """
    conflicts = []
    slot_label, start_time, end_time = slot_info
    
    # Check student conflicts
    for course_id in course_group:
        student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
        for student_id in student_ids:
            current_exam_dates = student_exam_dates.get(student_id, [])
            if proposed_date in current_exam_dates:
                conflicts.append(f"Student {student_id} already has exam on {proposed_date}")
    
    # Check room capacity
    total_students = sum(
        Enrollment.objects.filter(course_id=course_id).count()
        for course_id in course_group
    )
    total_capacity = get_total_room_capacity()
    if total_students > total_capacity:
        conflicts.append(
            f"Insufficient room capacity: {total_students} students needed, {total_capacity} available"
        )
    
    return len(conflicts) == 0, conflicts

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate exam schedule by grouping compatible courses and maximizing room usage
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    # Get course conflict matrix and compatible course groups
    conflict_matrix = analyze_student_course_conflicts()
    course_groups = find_compatible_courses(conflict_matrix)
    
    # Filter by course_ids if provided
    if course_ids:
        course_groups = [
            [course_id for course_id in group if course_id in course_ids]
            for group in course_groups
        ]
        course_groups = [group for group in course_groups if group]
    
    # Calculate minimum days needed
    slots_per_day = 2 if start_date.strftime('%A') == 'Friday' else 3
    min_days_needed = (len(course_groups) + slots_per_day - 1) // slots_per_day
    
    # Generate slots for more days to ensure scheduling feasibility
    date_slots = get_exam_slots(start_date, max_days=min_days_needed + 7)  # Add buffer
    
    # Group slots by date
    slots_by_date = defaultdict(list)
    for slot_idx, (date, label, start, end) in enumerate(date_slots):
        slots_by_date[date].append((slot_idx, label, start, end))

    exams_created = []
    student_exam_dates = defaultdict(list)
    assigned_slots = set()
    
    with transaction.atomic():
        # Sort course groups by size
        group_info = []
        for i, course_group in enumerate(course_groups):
            total_students = sum(
                Enrollment.objects.filter(course_id=course_id).count()
                for course_id in course_group
            )
            preference = GROUP_PREFERENCES.get(
                get_course_group(Course.objects.get(id=course_group[0])),
                "mixed"
            )
            group_info.append((i, total_students, preference, course_group))
        
        group_info.sort(key=lambda x: x[1], reverse=True)
        
        # Try scheduling each course group
        unscheduled_groups = []
        for group_idx, total_students, preference, course_group in group_info:
            # Get preferred slots
            slot_priority = {'Morning': 0, 'Afternoon': 1, 'Evening': 2}
            if preference == "mostly morning":
                preferred_slot_order = [0, 1, 2]
            elif preference == "evening":
                preferred_slot_order = [2, 1, 0]
            else:
                preferred_slot_order = [0, 1, 2]
                if random.random() < 0.5:
                    random.shuffle(preferred_slot_order)
            
            scheduled = False
            for date in sorted(slots_by_date.keys()):
                if scheduled:
                    break
                
                available_slots = [
                    (slot_idx, label, start, end)
                    for slot_idx, label, start, end in slots_by_date[date]
                    if slot_idx not in assigned_slots
                ]
                
                # Filter slots for Friday
                weekday = date.strftime('%A')
                if weekday == 'Friday':
                    available_slots = [s for s in available_slots if s[1] in ['Morning', 'Afternoon']]
                
                # Sort by preference
                available_slots.sort(key=lambda x: preferred_slot_order[slot_priority[x[1]]])
                
                for slot_idx, label, start_time, end_time in available_slots:
                    can_schedule, conflicts = can_schedule_course_group_on_slot(
                        course_group, date, (label, start_time, end_time), student_exam_dates
                    )
                    
                    if can_schedule:
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
                            
                            student_ids = Enrollment.objects.filter(course=course).values_list('student_id', flat=True)
                            for student_id in student_ids:
                                student_exam_dates[student_id].append(date)
                                student_exam_dates[student_id].sort()
                        
                        assigned_slots.add(slot_idx)
                        
                        try:
                            unaccommodated = allocate_shared_rooms(group_exams)
                            print(f"Scheduled {preference} group {course_group} on {date} {label} ({start_time}-{end_time})")
                            if unaccommodated:
                                print(f"  Warning: {len(unaccommodated)} students unaccommodated")
                        except Exception as e:
                            print(f"  Room allocation error: {e}")
                            for exam in group_exams:
                                exam.delete()
                            raise ValueError(f"Room allocation failed for group {course_group}")
                        
                        scheduled = True
                        break
                
                if not scheduled:
                    print(f"Could not schedule {preference} group {course_group}, adding to unscheduled")
                    unscheduled_groups.append((course_group, preference))
            
            # Handle unscheduled groups by splitting them
            while unscheduled_groups:
                course_group, preference = unscheduled_groups.pop(0)
                if len(course_group) <= 1:
                    raise ValueError(f"Cannot schedule single course {course_group}")
                
                # Split into smaller subgroups
                subgroups = split_course_group(course_group, conflict_matrix)
                print(f"Split group {course_group} into subgroups: {subgroups}")
                
                for subgroup in subgroups:
                    scheduled = False
                    for date in sorted(slots_by_date.keys()):
                        if scheduled:
                            break
                        available_slots = [
                            (slot_idx, label, start, end)
                            for slot_idx, label, start, end in slots_by_date[date]
                            if slot_idx in assigned_slots
                        ]
                        if weekday == 'Friday':
                            available_slots = [s for s in available_slots if s[1] in ['Morning', 'Afternoon']]
                        available_slots.sort(key=lambda x: preferred_slot_order[slot_priority[x[1]]])
                        
                        for slot_idx, label, start_time, end_time in available_slots:
                            can_schedule, conflicts = can_schedule_course_group_on_slot(
                                subgroup, date, (label, start_time, end_time), student_exam_dates
                            )
                            if can_schedule:
                                group_exams = []
                                for course_id in subgroup:
                                    course = Course.objects.get(id=course_id)
                                    exam = Exam.objects.create(
                                        course=course,
                                        date=date,
                                        start_time=start_time,
                                        end_time=end_time
                                    )
                                    exams_created.append(exam)
                                    group_exams.append(exam)
                                    
                                    student_ids = Enrollment.objects.filter(course=course).values_list('student_id', flat=True)
                                    for student_id in student_ids:
                                        student_exam_dates[student_id].append(date)
                                        student_exam_dates[student_id].sort()
                                
                                assigned_slots.add(slot_idx)
                                
                                try:
                                    unaccommodated = allocate_shared_rooms(group_exams)
                                    print(f"Scheduled {preference} subgroup {subgroup} on {date} {label} ({start_time}-{end_time})")
                                    if unaccommodated:
                                        print(f"  Warning: {len(unaccommodated)} students unaccommodated")
                                except Exception as e:
                                    print(f"  Room allocation error: {e}")
                                    for exam in group_exams:
                                        exam.delete()
                                    raise ValueError(f"Room allocation failed for subgroup {subgroup}")
                                
                                scheduled = True
                                break
                    
                    if not scheduled:
                        unscheduled_groups.append((subgroup, preference))
    
    return exams_created, None

def verify_day_off_constraints(min_gap_days=2):
    """
    Verify that the schedule maintains day-off constraints
    """
    violations = []
    student_exam_dates = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exam_dates[student_exam.student.id].append(student_exam.exam.date)
    
    for student_id, exam_dates in student_exam_dates.items():
        if len(exam_dates) < 2:
            continue
        sorted_dates = sorted(exam_dates)
        for i in range(len(sorted_dates) - 1):
            gap = (sorted_dates[i + 1] - sorted_dates[i]).days
            if gap < min_gap_days:
                violations.append(f"Student {student_id}: {gap} day gap between {sorted_dates[i]} and {sorted_dates[i + 1]}")
    
    return violations

def allocate_single_exam_rooms(exam):
    """
    Allocate students to rooms for a single exam
    """
    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    student_exam_qs = StudentExam.objects.filter(exam=exam).select_related('student')
    unassigned = list(student_exam_qs)
    random.shuffle(unassigned)
    
    total_students = len(unassigned)
    available_capacity = sum(r.capacity for r in rooms)
    unaccommodated_students = []
    
    if total_students > available_capacity:
        accommodated_count = available_capacity
        unaccommodated_students = [se.student for se in unassigned[accommodated_count:]]
        unassigned = unassigned[:accommodated_count]
    
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
    """
    with transaction.atomic():
        StudentExam.objects.filter(exam_id=exam_id).delete()
        Exam.objects.filter(id=exam_id).delete()
    return True

def reschedule_exam(exam_id, new_date, slot=None):
    """
    Reschedule an exam with comprehensive validation
    """
    with transaction.atomic():
        exam = Exam.objects.get(id=exam_id)
        original_date = exam.date
        original_start_time = exam.start_time
        original_end_time = exam.end_time
        
        weekday = new_date.strftime('%A')
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")
        
        new_start_time = exam.start_time
        new_end_time = exam.end_time
        if slot:
            available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
            slot_match = next((s for s in available_slots if s[0].lower() == slot.lower()), None)
            if not slot_match:
                available_slot_names = [s[0] for s in available_slots]
                raise ValueError(
                    f"Invalid slot '{slot}' for {weekday}. "
                    f"Available slots: {', '.join(available_slot_names)}"
                )
            _, new_start_time, new_end_time = slot_match
        else:
            current_slot = (exam.start_time, exam.end_time)
            friday_times = [(start, end) for _, start, end in FRIDAY_SLOTS]
            if weekday == 'Friday' and current_slot not in friday_times:
                available_slots = [f"{label} ({start}-{end})" for label, start, end in FRIDAY_SLOTS]
                raise ValueError(
                    f"Current time slot is not valid for Friday. "
                    f"Available Friday slots: {', '.join(available_slots)}."
                )
        
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
        
        exam_student_count = Enrollment.objects.filter(course=exam.course).count()
        existing_slot_exams = Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ).exclude(id=exam_id)
        
        total_students_needed = exam_student_count
        other_exams_students = 0
        for other_exam in existing_slot_exams:
            other_exam_students = Enrollment.objects.filter(course=other_exam.course).count()
            other_exams_students += other_exam_students
            total_students_needed += other_exam_students
        
        total_room_capacity = get_total_room_capacity()
        if total_students_needed > total_room_capacity:
            raise ValueError(
                f"Insufficient room capacity. Required: {total_students_needed} students, "
                f"Available: {total_room_capacity} seats."
            )
        
        exam_students = set(Enrollment.objects.filter(course=exam.course).values_list('student_id', flat=True))
        for other_exam in existing_slot_exams:
            other_students = set(Enrollment.objects.filter(course=other_exam.course).values_list('student_id', flat=True))
            common_students = exam_students.intersection(other_students)
            if common_students:
                raise ValueError(
                    f"Course compatibility conflict: {len(common_students)} student(s) are enrolled in both "
                    f"'{exam.course.name}' and '{other_exam.course.name}'."
                )
        
        all_slot_exams = list(existing_slot_exams) + [exam]
        room_requirements = [Enrollment.objects.filter(course=slot_exam.course).count() for slot_exam in all_slot_exams]
        rooms = list(Room.objects.order_by('-capacity'))
        if not can_accommodate_exams(room_requirements, rooms):
            raise ValueError("Cannot allocate rooms efficiently for all exams in this slot.")
        
        exam.date = new_date
        exam.start_time = new_start_time
        exam.end_time = new_end_time
        exam.save()
        
        slot_exams = list(Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ))
        StudentExam.objects.filter(exam__in=slot_exams).update(room=None)
        
        try:
            unaccommodated = allocate_shared_rooms(slot_exams)
            if unaccommodated:
                exam.date = original_date
                exam.start_time = original_start_time
                exam.end_time = original_end_time
                exam.save()
                raise ValueError(
                    f"Room allocation failed: {len(unaccommodated)} students could not be accommodated."
                )
        except Exception as e:
            exam.date = original_date
            exam.start_time = original_start_time
            exam.end_time = original_end_time
            exam.save()
            raise ValueError(f"Room allocation error: {str(e)}")
    
    return exam

def can_accommodate_exams(student_counts, rooms):
    """
    Check if student counts can be accommodated in available rooms
    """
    if not rooms:
        return False
    
    total_students = sum(student_counts)
    total_capacity = sum(room.capacity for room in rooms)
    if total_students > total_capacity:
        return False
    
    sorted_counts = sorted(student_counts, reverse=True)
    sorted_rooms = sorted(rooms, key=lambda r: r.capacity, reverse=True)
    room_remaining = [room.capacity for room in sorted_rooms]
    
    for count in sorted_counts:
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
    """
    exam = Exam.objects.get(id=exam_id)
    current_date = exam.date
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
        
        available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
        for slot_name, start_time, end_time in available_slots:
            try:
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
                continue
        current += timedelta(days=1)
    
    return suggestions

def check_reschedule_feasibility(exam_id, new_date, slot_name):
    """
    Check if rescheduling is feasible
    """
    conflicts = []
    exam = Exam.objects.get(id=exam_id)
    weekday = new_date.strftime('%A')
    
    if weekday in NO_EXAM_DAYS:
        conflicts.append(f"Cannot schedule on {weekday}")
        return conflicts
    
    available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
    slot_match = next((s for s in available_slots if s[0].lower() == slot_name.lower()), None)
    if not slot_match:
        conflicts.append(f"Invalid slot '{slot_name}' for {weekday}")
        return conflicts
    
    _, new_start_time, new_end_time = slot_match
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
    
    return conflicts

def get_unaccommodated_students():
    """
    Get list of unaccommodated students
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

def find_optimal_exam_dates(start_date=None):
    """
    Find optimal dates for scheduling exams
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    conflict_matrix = analyze_student_course_conflicts()
    course_groups = find_compatible_courses(conflict_matrix)
    
    slots_per_day = 2 if start_date.strftime('%A') == 'Friday' else 3
    min_days_needed = (len(course_groups) + slots_per_day - 1) // slots_per_day
    
    date_slots = get_exam_slots(start_date, max_days=min_days_needed + 7)
    
    return {
        'start_date': start_date,
        'suggested_end_date': start_date + timedelta(days=min_days_needed + 2),
        'min_days_needed': min_days_needed,
        'course_groups': course_groups,
        'available_slots': date_slots[:min_days_needed * slots_per_day]
    }

def verify_exam_schedule():
    """
    Verify that the current exam schedule has no conflicts
    """
    conflicts = []
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
    
        if len(slot_exams) < 2:
            continue
        for i, exam1 in enumerate(slot_exams):
            for exam2 in slot_exams[i+1:]:
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