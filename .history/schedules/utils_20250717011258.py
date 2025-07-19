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

def analyze_student_course_conflicts():
    """Analyze which courses have students in common"""
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

def find_all_compatible_course_groups():
    """
    Find ALL possible compatible course groups to maximize room utilization
    """
    # Get conflict matrix
    conflict_matrix = analyze_student_course_conflicts()
    
    # Get all courses with enrollments
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count('enrollments')
    ).filter(enrollment_count__gt=0)
    
    all_course_ids = set(enrolled_courses.values_list('id', flat=True))
    
    # Build compatibility graph
    compatibility_graph = {course: set() for course in all_course_ids}
    for course1 in all_course_ids:
        for course2 in all_course_ids:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                # Courses are compatible if they don't share students
                if pair not in conflict_matrix or conflict_matrix[pair] == 0:
                    compatibility_graph[course1].add(course2)
    
    # Find maximal compatible groups using improved greedy algorithm
    remaining_courses = set(all_course_ids)
    course_groups = []
    
    while remaining_courses:
        # Start with course that has most constraints (fewest compatible courses)
        start_course = min(
            remaining_courses,
            key=lambda c: len(compatibility_graph[c] & remaining_courses)
        )
        
        current_group = [start_course]
        remaining_courses.remove(start_course)
        
        # Find all courses compatible with ALL courses in current group
        compatible_with_all = set(compatibility_graph[start_course]) & remaining_courses
        
        # Keep adding compatible courses to maximize group size
        while compatible_with_all:
            # Choose course with most students to prioritize high-enrollment courses
            next_course = max(
                compatible_with_all,
                key=lambda c: Enrollment.objects.filter(course_id=c).count()
            )
            
            current_group.append(next_course)
            remaining_courses.remove(next_course)
            
            # Update compatible set - only courses compatible with ALL in group
            new_compatible = set()
            for candidate in compatible_with_all:
                if candidate == next_course:
                    continue
                if candidate in compatibility_graph[next_course]:
                    new_compatible.add(candidate)
            
            compatible_with_all = new_compatible & remaining_courses
        
        course_groups.append(current_group)
    
    return course_groups

def get_course_group_preference(course_ids):
    """Get the most common preference for a group of courses"""
    preferences = []
    for course_id in course_ids:
        course = Course.objects.get(id=course_id)
        group = get_course_group(course)
        preference = GROUP_PREFERENCES.get(group, "mixed")
        preferences.append(preference)
    
    # Return most common preference
    from collections import Counter
    return Counter(preferences).most_common(1)[0][0]

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

def get_exam_slots(start_date, max_slots=None):
    """Generate available exam slots"""
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

def get_total_room_capacity():
    """Get total capacity of all rooms"""
    return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0

def calculate_optimal_days(course_groups):
    """Calculate optimal number of days based on room capacity and groups"""
    total_room_capacity = get_total_room_capacity()
    
    # Calculate total students per group
    group_student_counts = []
    for group in course_groups:
        total_students = sum(
            Enrollment.objects.filter(course_id=course_id).count()
            for course_id in group
        )
        group_student_counts.append(total_students)
    
    # Sort groups by student count (largest first)
    group_student_counts.sort(reverse=True)
    
    # Calculate how many groups can fit per day
    groups_per_day = 0
    current_day_capacity = 0
    
    for i, student_count in enumerate(group_student_counts):
        if current_day_capacity + student_count <= total_room_capacity:
            current_day_capacity += student_count
            groups_per_day += 1
        else:
            break
    
    if groups_per_day == 0:
        groups_per_day = 1  # At least one group per day
    
    # Calculate minimum days needed
    min_days = (len(course_groups) + groups_per_day - 1) // groups_per_day
    
    return min_days, groups_per_day

def improved_room_allocation(exams):
    """
    Improved room allocation following the specified rules:
    1. Each room hosts maximum 2 courses from different semesters (1+ semester gap)
    2. Students split equally between courses in same room
    3. Overflow goes to next room
    4. Prioritize 2 courses per room
    """
    if not exams:
        return []

    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    # Get student counts and semester info for each exam
    exam_info = []
    for exam in exams:
        students = list(Enrollment.objects.filter(course=exam.course).select_related('student'))
        semester = getattr(exam.course, 'semester', None)
        semester_num = 1  # Default
        
        if semester and hasattr(semester, 'name'):
            try:
                semester_num = int(semester.name.split(" ")[1])
            except:
                semester_num = 1
        
        exam_info.append({
            'exam': exam,
            'students': students,
            'semester': semester_num,
            'remaining_students': students.copy()
        })

    # Sort exams by semester to help with pairing
    exam_info.sort(key=lambda x: x['semester'])
    
    assigned_student_exams = []
    unaccommodated_students = []
    room_index = 0
    
    # Try to pair exams with sufficient semester gap
    used_exams = set()
    exam_pairs = []
    
    for i, exam1_info in enumerate(exam_info):
        if exam1_info['exam'].id in used_exams:
            continue
            
        best_pair = None
        best_gap = 0
        
        for j, exam2_info in enumerate(exam_info[i+1:], i+1):
            if exam2_info['exam'].id in used_exams:
                continue
                
            semester_gap = abs(exam1_info['semester'] - exam2_info['semester'])
            if semester_gap >= 2 and semester_gap > best_gap:
                best_pair = exam2_info
                best_gap = semester_gap
        
        if best_pair:
            exam_pairs.append((exam1_info, best_pair))
            used_exams.add(exam1_info['exam'].id)
            used_exams.add(best_pair['exam'].id)
        else:
            exam_pairs.append((exam1_info, None))
            used_exams.add(exam1_info['exam'].id)

    # Allocate rooms for each pair
    for pair in exam_pairs:
        if room_index >= len(rooms):
            # No more rooms - add remaining students to unaccommodated
            for exam_info_item in pair:
                if exam_info_item:
                    unaccommodated_students.extend([s.student for s in exam_info_item['remaining_students']])
            continue

        room = rooms[room_index]
        room_capacity = room.capacity
        
        if pair[1] is None:  # Single exam
            exam_info_item = pair[0]
            students_to_allocate = exam_info_item['remaining_students'][:room_capacity]
            
            for enrollment in students_to_allocate:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam_info_item['exam'], room=room)
                )
            
            # Update remaining students
            exam_info_item['remaining_students'] = exam_info_item['remaining_students'][room_capacity:]
            
        else:  # Two exams
            exam1_info, exam2_info = pair
            
            # Split capacity equally
            capacity_per_exam = room_capacity // 2
            
            # Allocate students from each exam
            students1 = exam1_info['remaining_students'][:capacity_per_exam]
            students2 = exam2_info['remaining_students'][:capacity_per_exam]
            
            for enrollment in students1:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam1_info['exam'], room=room)
                )
            
            for enrollment in students2:
                assigned_student_exams.append(
                    StudentExam(student=enrollment.student, exam=exam2_info['exam'], room=room)
                )
            
            # Update remaining students
            exam1_info['remaining_students'] = exam1_info['remaining_students'][capacity_per_exam:]
            exam2_info['remaining_students'] = exam2_info['remaining_students'][capacity_per_exam:]
        
        room_index += 1

    # Handle remaining students from overflow
    while room_index < len(rooms):
        room = rooms[room_index]
        room_capacity = room.capacity
        
        # Find exams with remaining students
        exams_with_remaining = [info for info in exam_info if info['remaining_students']]
        
        if not exams_with_remaining:
            break
        
        # Try to pair two exams with remaining students
        if len(exams_with_remaining) >= 2:
            # Find best pair with semester gap
            best_pair = None
            best_gap = 0
            
            for i, exam1_info in enumerate(exams_with_remaining):
                for exam2_info in exams_with_remaining[i+1:]:
                    semester_gap = abs(exam1_info['semester'] - exam2_info['semester'])
                    if semester_gap >= 2 and semester_gap > best_gap:
                        best_pair = (exam1_info, exam2_info)
                        best_gap = semester_gap
            
            if best_pair:
                exam1_info, exam2_info = best_pair
                capacity_per_exam = room_capacity // 2
                
                students1 = exam1_info['remaining_students'][:capacity_per_exam]
                students2 = exam2_info['remaining_students'][:capacity_per_exam]
                
                for enrollment in students1:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam1_info['exam'], room=room)
                    )
                
                for enrollment in students2:
                    assigned_student_exams.append(
                        StudentExam(student=enrollment.student, exam=exam2_info['exam'], room=room)
                    )
                
                exam1_info['remaining_students'] = exam1_info['remaining_students'][capacity_per_exam:]
                exam2_info['remaining_students'] = exam2_info['remaining_students'][capacity_per_exam:]
                
                room_index += 1
                continue
        
        # If no good pair found, allocate single exam
        exam_info_item = exams_with_remaining[0]
        students_to_allocate = exam_info_item['remaining_students'][:room_capacity]
        
        for enrollment in students_to_allocate:
            assigned_student_exams.append(
                StudentExam(student=enrollment.student, exam=exam_info_item['exam'], room=room)
            )
        
        exam_info_item['remaining_students'] = exam_info_item['remaining_students'][room_capacity:]
        room_index += 1

    # Add any remaining unaccommodated students
    for exam_info_item in exam_info:
        unaccommodated_students.extend([s.student for s in exam_info_item['remaining_students']])

    # Save all assignments
    StudentExam.objects.bulk_create(assigned_student_exams)
    
    return unaccommodated_students

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate improved exam schedule that maximizes room utilization
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    print("Finding all compatible course groups...")
    all_course_groups = find_all_compatible_course_groups()
    
    # Filter by course_ids if provided
    if course_ids:
        filtered_groups = []
        for group in all_course_groups:
            filtered_group = [cid for cid in group if cid in course_ids]
            if filtered_group:
                filtered_groups.append(filtered_group)
        all_course_groups = filtered_groups
    
    print(f"Found {len(all_course_groups)} compatible course groups")
    for i, group in enumerate(all_course_groups):
        group_size = sum(Enrollment.objects.filter(course_id=cid).count() for cid in group)
        print(f"Group {i+1}: {len(group)} courses, {group_size} students")
    
    # Calculate optimal scheduling
    min_days, groups_per_day = calculate_optimal_days(all_course_groups)
    total_room_capacity = get_total_room_capacity()
    
    print(f"Optimal scheduling: {min_days} days, ~{groups_per_day} groups per day")
    print(f"Total room capacity: {total_room_capacity}")
    
    # Generate enough slots
    estimated_slots_needed = len(all_course_groups) * 2  # Buffer
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
    
    # Group slots by date
    slots_by_date = defaultdict(list)
    for slot_idx, (date, label, start, end) in enumerate(date_slots):
        slots_by_date[date].append((slot_idx, label, start, end))
    
    exams_created = []
    assigned_slots = set()
    
    with transaction.atomic():
        # Sort groups by total students (largest first) and preference
        group_info = []
        for group in all_course_groups:
            total_students = sum(
                Enrollment.objects.filter(course_id=cid).count() 
                for cid in group
            )
            preference = get_course_group_preference(group)
            group_info.append((group, total_students, preference))
        
        # Sort by student count (descending) to prioritize large groups
        group_info.sort(key=lambda x: x[1], reverse=True)
        
        # Schedule each group
        for group, total_students, preference in group_info:
            print(f"\nScheduling group with {len(group)} courses, {total_students} students, {preference} preference")
            
            # Determine slot preference order
            if preference == "mostly morning":
                slot_order = [0, 1, 2]  # Morning, Afternoon, Evening
            elif preference == "evening":
                slot_order = [2, 1, 0]  # Evening, Afternoon, Morning
            else:
                slot_order = [0, 1, 2]  # Default order
            
            scheduled = False
            
            # Try each date
            for date in sorted(slots_by_date.keys()):
                if scheduled:
                    break
                
                weekday = date.strftime('%A')
                available_slots = [
                    (slot_idx, label, start, end) 
                    for slot_idx, label, start, end in slots_by_date[date]
                    if slot_idx not in assigned_slots
                ]
                
                # Apply Friday restrictions
                if weekday == 'Friday':
                    available_slots = [s for s in available_slots if s[1] in ['Morning', 'Afternoon']]
                
                # Sort by preference
                slot_priority = {'Morning': 0, 'Afternoon': 1, 'Evening': 2}
                available_slots.sort(key=lambda x: slot_order.index(slot_priority[x[1]]))
                
                # Try each slot
                for slot_idx, label, start_time, end_time in available_slots:
                    # Check if this slot can accommodate the group
                    if total_students <= total_room_capacity:
                        # Create exams for all courses in the group
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
                        
                        # Allocate rooms using improved algorithm
                        try:
                            unaccommodated = improved_room_allocation(group_exams)
                            assigned_slots.add(slot_idx)
                            
                            print(f"✓ Scheduled on {date} {label} ({start_time}-{end_time})")
                            if unaccommodated:
                                print(f"  Warning: {len(unaccommodated)} students unaccommodated")
                            
                            scheduled = True
                            break
                            
                        except Exception as e:
                            print(f"  Room allocation failed: {e}")
                            # Clean up created exams
                            for exam in group_exams:
                                exam.delete()
                            exams_created = [e for e in exams_created if e not in group_exams]
            
            if not scheduled:
                print(f"✗ Could not schedule group with {total_students} students")
                raise ValueError(f"Cannot find suitable slot for group with {total_students} students")
    
    print(f"\nScheduling complete: {len(exams_created)} exams created")
    return exams_created

# Additional utility functions
def get_schedule_statistics():
    """Get statistics about the current schedule"""
    total_exams = Exam.objects.count()
    total_students = StudentExam.objects.count()
    unaccommodated = StudentExam.objects.filter(room__isnull=True).count()
    
    # Room utilization
    room_usage = defaultdict(int)
    for student_exam in StudentExam.objects.select_related('room'):
        if student_exam.room:
            room_usage[student_exam.room.id] += 1
    
    room_utilization = []
    for room in Room.objects.all():
        usage = room_usage[room.id]
        utilization = (usage / room.capacity) * 100 if room.capacity > 0 else 0
        room_utilization.append({
            'room': room.name,
            'capacity': room.capacity,
            'used': usage,
            'utilization': utilization
        })
    
    return {
        'total_exams': total_exams,
        'total_students': total_students,
        'unaccommodated': unaccommodated,
        'accommodation_rate': ((total_students - unaccommodated) / total_students * 100) if total_students > 0 else 0,
        'room_utilization': room_utilization
    }

def print_schedule_summary():
    """Print a summary of the generated schedule"""
    stats = get_schedule_statistics()
    
    print("\n" + "="*50)
    print("EXAM SCHEDULE SUMMARY")
    print("="*50)
    print(f"Total Exams: {stats['total_exams']}")
    print(f"Total Students: {stats['total_students']}")
    print(f"Unaccommodated: {stats['unaccommodated']}")
    print(f"Accommodation Rate: {stats['accommodation_rate']:.1f}%")
    
    print("\nRoom Utilization:")
    for room_info in stats['room_utilization']:
        print(f"  {room_info['room']}: {room_info['used']}/{room_info['capacity']} ({room_info['utilization']:.1f}%)")
    
    print("\nSchedule by Date:")
    exams_by_date = defaultdict(list)
    for exam in Exam.objects.all().order_by('date', 'start_time'):
        exams_by_date[exam.date].append(exam)
    
    for date, exams in sorted(exams_by_date.items()):
        print(f"\n{date} ({date.strftime('%A')}):")
        for exam in exams:
            student_count = StudentExam.objects.filter(exam=exam).count()
            print(f"  {exam.start_time}-{exam.end_time}: {exam.course.name} ({student_count} students)")



# ... (keep all the existing constants and helper functions) ...

def analyze_student_course_conflicts():
    """Analyze which courses have students in common"""
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

def get_student_exam_dates(student_id, scheduled_exams):
    """Get all exam dates for a student from scheduled exams"""
    dates = set()
    for exam in scheduled_exams:
        if StudentExam.objects.filter(exam=exam, student_id=student_id).exists():
            dates.add(exam.date)
    return dates

def generate_exam_schedule(start_date=None, course_ids=None):
    """
    Generate improved exam schedule that maximizes room utilization
    and ensures no student has more than one exam per day.
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)
    
    print("Finding all compatible course groups...")
    all_course_groups = find_all_compatible_course_groups()
    
    # Filter by course_ids if provided
    if course_ids:
        filtered_groups = []
        for group in all_course_groups:
            filtered_group = [cid for cid in group if cid in course_ids]
            if filtered_group:
                filtered_groups.append(filtered_group)
        all_course_groups = filtered_groups
    
    print(f"Found {len(all_course_groups)} compatible course groups")
    for i, group in enumerate(all_course_groups):
        group_size = sum(Enrollment.objects.filter(course_id=cid).count() for cid in group)
        print(f"Group {i+1}: {len(group)} courses, {group_size} students")
    
    # Calculate optimal scheduling
    min_days, groups_per_day = calculate_optimal_days(all_course_groups)
    total_room_capacity = get_total_room_capacity()
    
    print(f"Optimal scheduling: {min_days} days, ~{groups_per_day} groups per day")
    print(f"Total room capacity: {total_room_capacity}")
    
    # Generate enough slots
    estimated_slots_needed = len(all_course_groups) * 2  # Buffer
    date_slots = get_exam_slots(start_date, max_slots=estimated_slots_needed)
    
    # Group slots by date
    slots_by_date = defaultdict(list)
    for slot_idx, (date, label, start, end) in enumerate(date_slots):
        slots_by_date[date].append((slot_idx, label, start, end))
    
    exams_created = []
    assigned_slots = set()
    
    with transaction.atomic():
        # Sort groups by total students (largest first) and preference
        group_info = []
        for group in all_course_groups:
            total_students = sum(
                Enrollment.objects.filter(course_id=cid).count() 
                for cid in group
            )
            preference = get_course_group_preference(group)
            group_info.append((group, total_students, preference))
        
        # Sort by student count (descending) to prioritize large groups
        group_info.sort(key=lambda x: x[1], reverse=True)
        
        # Track student exam dates
        student_exam_dates = defaultdict(set)
        
        # Schedule each group
        for group, total_students, preference in group_info:
            print(f"\nScheduling group with {len(group)} courses, {total_students} students, {preference} preference")
            
            # Determine slot preference order
            if preference == "mostly morning":
                slot_order = [0, 1, 2]  # Morning, Afternoon, Evening
            elif preference == "evening":
                slot_order = [2, 1, 0]  # Evening, Afternoon, Morning
            else:
                slot_order = [0, 1, 2]  # Default order
            
            scheduled = False
            
            # Try each date
            for date in sorted(slots_by_date.keys()):
                if scheduled:
                    break
                
                weekday = date.strftime('%A')
                available_slots = [
                    (slot_idx, label, start, end) 
                    for slot_idx, label, start, end in slots_by_date[date]
                    if slot_idx not in assigned_slots
                ]
                
                # Apply Friday restrictions
                if weekday == 'Friday':
                    available_slots = [s for s in available_slots if s[1] in ['Morning', 'Afternoon']]
                
                # Sort by preference
                slot_priority = {'Morning': 0, 'Afternoon': 1, 'Evening': 2}
                available_slots.sort(key=lambda x: slot_order.index(slot_priority[x[1]]))
                
                # Try each slot
                for slot_idx, label, start_time, end_time in available_slots:
                    # Check if this slot can accommodate the group
                    if total_students <= total_room_capacity:
                        # Get all students in this group
                        group_students = set()
                        for course_id in group:
                            enrollments = Enrollment.objects.filter(course_id=course_id)
                            group_students.update(e.student_id for e in enrollments)
                        
                        # Check if any student already has an exam on this date
                        conflicting_students = [
                            student_id for student_id in group_students
                            if date in student_exam_dates[student_id]
                        ]
                        
                        if conflicting_students:
                            print(f"  {len(conflicting_students)} students would have conflict on {date}")
                            continue  # Skip this slot if conflicts exist
                        
                        # Create exams for all courses in the group
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
                        
                        # Allocate rooms using improved algorithm
                        try:
                            unaccommodated = improved_room_allocation(group_exams)
                            assigned_slots.add(slot_idx)
                            
                            # Update student exam dates
                            for exam in group_exams:
                                student_ids = Enrollment.objects.filter(
                                    course=exam.course
                                ).values_list('student_id', flat=True)
                                for student_id in student_ids:
                                    student_exam_dates[student_id].add(exam.date)
                            
                            print(f"✓ Scheduled on {date} {label} ({start_time}-{end_time})")
                            if unaccommodated:
                                print(f"  Warning: {len(unaccommodated)} students unaccommodated")
                            
                            scheduled = True
                            break
                            
                        except Exception as e:
                            print(f"  Room allocation failed: {e}")
                            # Clean up created exams
                            for exam in group_exams:
                                exam.delete()
                            exams_created = [e for e in exams_created if e not in group_exams]
            
            if not scheduled:
                print(f"✗ Could not schedule group with {total_students} students")
                raise ValueError(f"Cannot find suitable slot for group with {total_students} students")
    
    print(f"\nScheduling complete: {len(exams_created)} exams created")
    return exams_created