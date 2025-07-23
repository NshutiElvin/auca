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
        compatible_groups=random.shuffle(compatible_groups)
        
        
        
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
from django.db import transaction
from datetime import time

def allocate_shared_rooms():
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
        # Data structure: {date: {slot: {room: [student_exams]}}}
        schedule = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        unaccommodated = []

        # Organize students by date and slot
        date_slot_students = defaultdict(lambda: defaultdict(list))
        for se in student_exams:
            for slot_name, start, end in SLOTS:
                if se.exam.start_time == start and se.exam.end_time == end:
                    date_slot_students[se.exam.date][slot_name].append(se)
                    break

        # Process each date and slot
        for date, slots in date_slot_students.items():
            for slot_name, slot_start, slot_end in SLOTS:
                student_exams = slots.get(slot_name, [])
                if not student_exams:
                    continue

                # Group by exam
                exams = defaultdict(list)
                for se in student_exams:
                    exams[se.exam].append(se)

                # Sort exams by student count (descending)
                sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))

                # Assign to rooms
                room_index = 0
                remaining_students = student_exams.copy()

                while remaining_students and room_index < len(rooms):
                    room = rooms[room_index]
                    room_index += 1

                    # Check if room is already used in this slot
                    if room.id in schedule[date][slot_name]:
                        continue

                    # Calculate available capacity
                    current_usage = len(schedule[date][slot_name].get(room.id, []))
                    available = room.capacity - current_usage

                    if available <= 0:
                        continue

                    # Try to find compatible exams to pair
                    best_pair = None
                    best_pair_size = 0

                    # Look for two exams that can share the room
                    for i in range(len(sorted_exams)):
                        exam1, students1 = sorted_exams[i]
                        if not students1:
                            continue
                        
                        for j in range(i+1, len(sorted_exams)):
                            exam2, students2 = sorted_exams[j]
                            if not students2:
                                continue
                            
                            # Check semester separation
                            sem1 = int(exam1.group.course.semester.name.split()[1])
                            sem2 = int(exam2.group.course.semester.name.split()[1])
                            if abs(sem1 - sem2) > 1:
                                pair_size = min(len(students1), len(students2), available//2)
                                if pair_size > best_pair_size:
                                    best_pair = (exam1, exam2, pair_size)
                                    best_pair_size = pair_size

                    if best_pair:
                        exam1, exam2, pair_size = best_pair
                        # Assign students from both exams
                        assigned = []
                        for exam in [exam1, exam2]:
                            exam_students = [se for se in remaining_students if se.exam == exam]
                            to_assign = exam_students[:pair_size]
                            assigned.extend(to_assign)
                            for se in to_assign:
                                remaining_students.remove(se)
                        schedule[date][slot_name][room.id].extend(assigned)
                    else:
                        # Assign single exam to room
                        exam, students = next(((e, s) for e, s in sorted_exams if s), (None, None))
                        if exam:
                            exam_students = [se for se in remaining_students if se.exam == exam]
                            to_assign = exam_students[:available]
                            schedule[date][slot_name][room.id].extend(to_assign)
                            for se in to_assign:
                                remaining_students.remove(se)

                # Track unassigned students
                unaccommodated.extend([se.student for se in remaining_students])

        # Save all assignments to database
        for date, slots in schedule.items():
            for slot_name, room_assignments in slots.items():
                for room_id, student_exams in room_assignments.items():
                    StudentExam.objects.filter(
                        id__in=[se.id for se in student_exams]
                    ).update(room_id=room_id)

        # Final attempt to place remaining students
        if unaccommodated:
            remaining_exams = StudentExam.objects.filter(
                student__in=unaccommodated,
                room__isnull=True
            ).select_related('exam')

            for se in remaining_exams:
                date = se.exam.date
                for slot_name, start, end in SLOTS:
                    if se.exam.start_time == start and se.exam.end_time == end:
                        # Find any room with space in this slot
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



 