from datetime import datetime, timedelta, time
from collections import defaultdict
import random
from django.db import transaction
from django.utils.timezone import now

from courses.models import Course
from exams.models import Exam, StudentExam
from enrollments.models import Enrollment
from rooms.models import Room

SLOTS = [
    ('Morning', time(9, 0), time(12, 0)),
    ('Evening', time(14, 0), time(17, 0)),
]
FRIDAY_SLOTS = [SLOTS[0]]
NO_EXAM_DAYS = ['Saturday', 'Sunday']

def get_exam_slots(start_date, max_slots=None):
    """
    Generate available exam slots starting from a specific date.
    Each slot consists of a date and time period.
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

def group_courses_by_pairs(course_ids=None):
    """
    Group courses into pairs that have no overlapping students.
    Each time slot must have exactly two exams.
    """
    course_students = defaultdict(set)

    enrollments_query = Enrollment.objects.select_related('student', 'course')
    if course_ids:
        enrollments_query = enrollments_query.filter(course_id__in=course_ids)

    # Map each course to its set of students
    for enrollment in enrollments_query:
        course_students[enrollment.course_id].add(enrollment.student_id)

    if course_ids:
        for course_id in course_ids:
            if course_id not in course_students:
                course_students[course_id] = set()

    course_ids = list(course_students.keys())
    
    # Create course pairs that don't have student conflicts
    grouped_pairs = []
    
    # Since we need exactly 2 courses per slot, we'll prioritize pairs with no conflicts
    remaining_courses = set(course_ids)
    
    while len(remaining_courses) >= 2:
        course_list = list(remaining_courses)
        found_pair = False
        
        for i in range(len(course_list)):
            if found_pair:
                break
                
            course1 = course_list[i]
            students1 = course_students[course1]
            
            for j in range(i+1, len(course_list)):
                course2 = course_list[j]
                students2 = course_students[course2]
                
                # Check if these courses have no overlapping students
                if students1.isdisjoint(students2):
                    grouped_pairs.append([course1, course2])
                    remaining_courses.remove(course1)
                    remaining_courses.remove(course2)
                    found_pair = True
                    break
        
        # If no conflict-free pair was found, just take the first two courses
        if not found_pair and len(remaining_courses) >= 2:
            first_two = list(remaining_courses)[:2]
            grouped_pairs.append(first_two)
            remaining_courses.remove(first_two[0])
            remaining_courses.remove(first_two[1])
    
    # Handle any remaining single course
    if remaining_courses:
        grouped_pairs.append(list(remaining_courses))
    
    return grouped_pairs

def generate_exam_schedule(start_date=None, course_ids=None):
    """
    Generate an exam schedule where:
    - Each slot has exactly two exams
    - Students have at most one exam per day
    - Rooms are shared between two courses
    """
    if not start_date:
        start_date = now().date() + timedelta(days=1)

    # Group courses into pairs for scheduling
    course_pairs = group_courses_by_pairs(course_ids)
    
    # Get date slots for exams
    date_slots = get_exam_slots(start_date, max_slots=len(course_pairs) * 2)
    
    exams_created = []
    student_exam_dates = defaultdict(set)  # Track exam dates per student
    unaccommodated_students = []  # Students who couldn't be assigned to rooms
    
    with transaction.atomic():
        # Assign slots to course pairs
        for pair in course_pairs:
            # Find a suitable date slot where no student has multiple exams
            suitable_slot = None
            for i, slot in enumerate(date_slots):
                exam_date, label, start_time, end_time = slot
                
                # Check if any student already has an exam on this date
                has_conflict = False
                for course_id in pair:
                    student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
                    for student_id in student_ids:
                        if exam_date in student_exam_dates[student_id]:
                            has_conflict = True
                            break
                    if has_conflict:
                        break
                
                if not has_conflict:
                    suitable_slot = slot
                    date_slots.pop(i)
                    break
            
            if not suitable_slot:
                raise ValueError("Cannot find suitable slot for all course pairs while maintaining schedule constraints.")
            
            exam_date, label, start_time, end_time = suitable_slot
            
            # Create exams for the course pair
            pair_exams = []
            for course_id in pair:
                course = Course.objects.get(id=course_id)
                
                exam = Exam.objects.create(
                    course=course,
                    date=exam_date,
                    start_time=start_time,
                    end_time=end_time
                )
                exams_created.append(exam)
                pair_exams.append(exam)
                
                # Update student exam dates for conflict checking
                students = Enrollment.objects.filter(course=course)
                for enrollment in students:
                    student_exam_dates[enrollment.student_id].add(exam_date)
        
            # Allocate rooms for the pair of exams
            unaccommodated = allocate_shared_rooms(pair_exams)
            unaccommodated_students.extend(unaccommodated)
    
    return exams_created, unaccommodated_students

def allocate_shared_rooms(exams):
    """
    Allocate rooms for a pair of exams, sharing each room between the two courses.
    Each room should be split equally between the two courses.
    Returns a list of students who couldn't be accommodated due to room capacity.
    """
    if not exams:
        return []
        
    if len(exams) == 1:
        # Only one exam to allocate, use the standard room allocation
        return allocate_single_exam_rooms(exams[0])
    
    rooms = list(Room.objects.order_by('-capacity'))  # Larger rooms first
    
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    # Get student enrollments for both exams
    student_exams_by_course = {}
    students_count_by_course = {}
    
    for exam in exams:
        # Create StudentExam records for all enrolled students
        enrolled_students = Enrollment.objects.filter(course=exam.course).select_related('student')
        
        student_exams = [
            StudentExam(student=e.student, exam=exam) for e in enrolled_students
        ]
        StudentExam.objects.bulk_create(student_exams)
        
        # Get all student exams for this course
        student_exam_qs = StudentExam.objects.filter(exam=exam).select_related('student')
        student_exams_by_course[exam.id] = list(student_exam_qs)
        students_count_by_course[exam.id] = len(student_exams_by_course[exam.id])
    
    # Calculate total needed capacity
    total_students = sum(students_count_by_course.values())
    total_capacity = sum(r.capacity for r in rooms)
    
    # Track unaccommodated students
    unaccommodated_students = []
    
    # If we don't have enough capacity, some students won't be accommodated
    if total_students > total_capacity:
        # Determine how many students we can accommodate
        accommodated_count = total_capacity
        # Calculate how many students from each course will be accommodated
        # (proportional to their total counts)
        accommodated_by_course = {}
        for exam_id, count in students_count_by_course.items():
            proportion = count / total_students
            accommodated_by_course[exam_id] = int(proportion * accommodated_count)
            
        # Make sure we don't exceed available capacity due to rounding
        total_accommodated = sum(accommodated_by_course.values())
        if total_accommodated < accommodated_count:
            # Distribute remaining seats
            remaining = accommodated_count - total_accommodated
            for exam_id in sorted(students_count_by_course.keys()):
                if remaining <= 0:
                    break
                accommodated_by_course[exam_id] += 1
                remaining -= 1
                
        # Determine which students will not be accommodated
        for exam_id, student_exams in student_exams_by_course.items():
            accommodated = accommodated_by_course[exam_id]
            if accommodated < len(student_exams):
                # Students who won't be accommodated
                unaccommodated = student_exams[accommodated:]
                unaccommodated_students.extend([se.student for se in unaccommodated])
                # Update the list to only include accommodated students
                student_exams_by_course[exam_id] = student_exams[:accommodated]
    
    # Allocate students to rooms, splitting each room between the two courses
    remaining_by_course = {exam_id: student_exams.copy() 
                          for exam_id, student_exams in student_exams_by_course.items()}
                          
    for room in rooms:
        # Calculate how many students from each course will go in this room
        students_per_course = {}
        remaining_capacity = room.capacity
        
        if len(exams) == 1:
            # If there's only one exam, put all students in the room
            exam_id = exams[0].id
            students_per_course[exam_id] = min(len(remaining_by_course[exam_id]), remaining_capacity)
            
        else:
            # Split the room capacity between courses (half and half)
            half_capacity = room.capacity // 2
            
            for exam_id, remaining in remaining_by_course.items():
                students_per_course[exam_id] = min(len(remaining), half_capacity)
                remaining_capacity -= students_per_course[exam_id]
            
            # If there's still capacity left, allocate it to courses that need more space
            for exam_id, remaining in sorted(remaining_by_course.items(), 
                                            key=lambda x: len(x[1]), reverse=True):
                if remaining_capacity > 0 and len(remaining) > students_per_course[exam_id]:
                    additional = min(remaining_capacity, len(remaining) - students_per_course[exam_id])
                    students_per_course[exam_id] += additional
                    remaining_capacity -= additional
        
        # Assign students to this room
        for exam_id, count in students_per_course.items():
            if count > 0:
                students_to_assign = remaining_by_course[exam_id][:count]
                for se in students_to_assign:
                    se.room = room
                    se.save(update_fields=['room'])
                    
                # Remove assigned students from remaining list
                remaining_by_course[exam_id] = remaining_by_course[exam_id][count:]
    
    # Check if there are still unassigned students (should not happen at this point)
    for exam_id, remaining in remaining_by_course.items():
        if remaining:
            unaccommodated_students.extend([se.student for se in remaining])
    
    return unaccommodated_students

def allocate_single_exam_rooms(exam):
    """
    Allocate rooms for a single exam.
    """
    rooms = list(Room.objects.order_by('-capacity'))  # Larger rooms first
    
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    # Get all StudentExam records for this exam
    student_exam_qs = StudentExam.objects.filter(exam=exam).select_related('student')
    unassigned = list(student_exam_qs)
    total_students = len(unassigned)
    
    available_capacity = sum(r.capacity for r in rooms)
    unaccommodated_students = []
    
    if total_students > available_capacity:
        # Not enough room capacity, some students won't be accommodated
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
    Cancel an exam and delete all related student exam records.
    """
    with transaction.atomic():
        StudentExam.objects.filter(exam_id=exam_id).delete()
        Exam.objects.filter(id=exam_id).delete()

    return True

def reschedule_exam(exam_id, new_date, new_start_time=None, new_end_time=None):
    """
    Reschedule an exam to a new date and time, ensuring no student has multiple
    exams on the same day.
    """
    with transaction.atomic():
        exam = Exam.objects.get(id=exam_id)
        
        weekday = new_date.strftime('%A')
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")
        
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        for enrollment in enrolled_students:
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student, 
                exam__date=new_date
            ).exclude(exam_id=exam_id)
            
            if existing_exams.exists():
                raise ValueError(
                    f"Student {enrollment.student.reg_no} already has an exam "
                    f"scheduled on {new_date}."
                )
        
        exam.date = new_date
        if new_start_time:
            exam.start_time = new_start_time
        if new_end_time:
            exam.end_time = new_end_time
            
        exam.save()

    return exam

def get_unaccommodated_students():
    """
    Get a list of students who couldn't be accommodated in the exam schedule.
    """
    # This function can be called to get the list of unaccommodated students
    # after running generate_exam_schedule
    pass







