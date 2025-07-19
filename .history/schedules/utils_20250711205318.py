# from datetime import timedelta, time
# from collections import defaultdict
# import random
# from django.db import transaction
# from django.utils.timezone import now
# from django.db.models import Sum

# from courses.models import Course
# from exams.models import Exam, StudentExam
# from enrollments.models import Enrollment
# from rooms.models import Room
# from django.db.models import Count
# SLOTS = [
#     ('Morning', time(8, 0), time(11, 0)),
#     ('Afternoon', time(13, 0), time(16, 0)),
#     ('Evening', time(17, 0), time(20, 0)),
# ]
# FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]   
# NO_EXAM_DAYS = ['Saturday']   

# def get_exam_slots(start_date, max_slots=None):
#     """
#     Generate a list of available exam slots starting from a given date.
#     Each slot is a tuple of (date, label, start_time, end_time)
#     """
#     date_slots = []
#     current_date = start_date

#     while max_slots is None or len(date_slots) < max_slots:
#         weekday = current_date.strftime('%A')
#         if weekday not in NO_EXAM_DAYS:
#             slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
#             for label, start, end in slots:
#                 date_slots.append((current_date, label, start, end))
#                 if max_slots and len(date_slots) >= max_slots:
#                     break
#         current_date += timedelta(days=1)

#     return date_slots

# def analyze_student_course_conflicts():
#     """
#     Analyze which courses have students in common to help with scheduling
#     Returns a dictionary where keys are course pairs and values are the count of students enrolled in both
#     """
#     conflict_matrix = defaultdict(int)
    
#     # Get all enrollments grouped by student
#     student_courses = defaultdict(list)
#     for enrollment in Enrollment.objects.all():
#         student_courses[enrollment.student_id].append(enrollment.course_id)
    
#     # Build conflict matrix
#     for student_id, courses in student_courses.items():
#         for i, course1 in enumerate(courses):
#             for course2 in courses[i+1:]:
#                 course_pair = tuple(sorted([course1, course2]))
#                 conflict_matrix[course_pair] += 1
    
#     return conflict_matrix

# def find_compatible_courses(course_conflict_matrix):
#     """
#     Group courses into compatible groups that can be scheduled together
#     Compatible means they don't share students
#     This function can group more than 2 courses per slot if they don't create conflicts
#     """
#     all_courses = set()
#     for course1, course2 in course_conflict_matrix.keys():
#         all_courses.add(course1)
#         all_courses.add(course2)
#     enrolled_courses = Course.objects.annotate(
#          enrollment_count=Count('enrollments')
#         ).filter(enrollment_count__gt=0)
    
#     # Add any courses that don't appear in the conflict matrix
#     for course in enrolled_courses.values_list('id', flat=True):
#         all_courses.add(course)
    
#     # Build adjacency list for course compatibility graph
#     # Two courses are compatible if they don't share any students
#     compatibility_graph = {course: set() for course in all_courses}
#     for course1 in all_courses:
#         for course2 in all_courses:
#             if course1 != course2:
#                 pair = tuple(sorted([course1, course2]))
#                 if pair not in course_conflict_matrix or course_conflict_matrix[pair] == 0:
#                     compatibility_graph[course1].add(course2)
    
#     # Group compatible courses using a greedy algorithm
#     remaining_courses = set(all_courses)
#     course_groups = []
    
#     while remaining_courses:
#         # Start a new group
#         course_group = []
        
#         # Pick a course with the fewest compatible options
#         if remaining_courses:
#             course1 = min(
#                 [c for c in remaining_courses],
#                 key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) \
#                     if len([rc for rc in compatibility_graph[c] if rc in remaining_courses]) > 0 \
#                     else float('inf')
#             )
            
#             course_group.append(course1)
#             remaining_courses.remove(course1)
            
#             # Keep track of courses that are compatible with ALL courses in our group
#             compatible_with_group = set(compatibility_graph[course1]) & remaining_courses
            
#             # Add more courses to the group if possible (greedy approach)
#             while compatible_with_group and len(course_group) < 10:  # Limit to 10 courses per group for practical reasons
#                 # Select the course with fewest remaining compatible options (to save harder-to-place courses for later)
#                 next_course = min(
#                     compatible_with_group,
#                     key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
#                 )
                
#                 course_group.append(next_course)
#                 remaining_courses.remove(next_course)
                
#                 # Update the set of courses compatible with the entire group
#                 compatible_with_group &= set(compatibility_graph[next_course])
#                 compatible_with_group &= remaining_courses
        
#         if course_group:
#             course_groups.append(course_group)
    
#     return course_groups

# def student_course_assignment(course_pairs):
#     """
#     For each student, determine which courses they're enrolled in from the given pairs
#     Returns a mapping of student_id -> list of (pair_index, course_id)
#     """
#     student_assignments = defaultdict(list)
    
#     for pair_index, pair in enumerate(course_pairs):
#         for course_id in pair:
#             enrollments = Enrollment.objects.filter(course_id=course_id)
#             for enrollment in enrollments:
#                 student_assignments[enrollment.student_id].append((pair_index, course_id))
    
#     return student_assignments

# def detect_scheduling_conflicts(course_pairs, student_assignments, date_slots):
#     """
#     Detect potential scheduling conflicts for each pair and slot
#     Returns a conflict score for each combination of pair and slot
#     Lower scores are better (fewer conflicts)
#     """
#     num_pairs = len(course_pairs)
#     num_slots = len(date_slots)
    
#     # Initialize conflict matrix
#     conflict_scores = [[0 for _ in range(num_slots)] for _ in range(num_pairs)]
    
#     # Group slots by date
#     slots_by_date = defaultdict(list)
#     for slot_idx, (date, label, start, end) in enumerate(date_slots):
#         slots_by_date[date].append(slot_idx)
    
#     # Calculate conflicts
#     for student_id, assignments in student_assignments.items():
#         # Check if student has multiple exams on the same day
#         for pair_indices, course_ids in assignments:
#             for pair_idx1, _ in assignments:
#                 if pair_idx1 != pair_indices:
#                     # These two course pairs can't be scheduled on the same day
#                     for date, slot_indices in slots_by_date.items():
#                         for slot_idx1 in slot_indices:
#                             for slot_idx2 in slot_indices:
#                                 conflict_scores[pair_idx1][slot_idx1] += 1
#                                 conflict_scores[pair_indices][slot_idx2] += 1
    
#     return conflict_scores

# def calculate_room_requirements(course_pairs):
#     """
#     Calculate how many students need to be accommodated for each course pair
#     Returns a list of dictionaries with course_id -> student_count
#     """
#     room_requirements = []
    
#     for pair in course_pairs:
#         pair_requirements = {}
#         for course_id in pair:
#             student_count = Enrollment.objects.filter(course_id=course_id).count()
#             pair_requirements[course_id] = student_count
#         room_requirements.append(pair_requirements)
    
#     return room_requirements

# def get_total_room_capacity():
#     """Get the total capacity of all available rooms"""
#     return Room.objects.aggregate(total_capacity=Sum('capacity'))['total_capacity'] or 0
 


# def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
  
#     if not start_date:
#         start_date = now().date() + timedelta(days=1)
    
#     conflict_matrix = analyze_student_course_conflicts()
#     course_pairs = find_compatible_courses(conflict_matrix)
    
#     if course_ids:
#         course_ids_set = set(course_ids)
#         filtered_pairs = []
#         for pair in course_pairs:
#             filtered_pair = [c for c in pair if c in course_ids_set]
#             if filtered_pair:
#                 filtered_pairs.append(filtered_pair)
#         course_pairs = filtered_pairs
    
#     date_slots = get_exam_slots(start_date, max_slots=len(course_pairs) * 3)  
    
#     student_assignments = student_course_assignment(course_pairs)
#     conflict_scores = detect_scheduling_conflicts(course_pairs, student_assignments, date_slots)
    
#     exams_created = []
#     student_exam_dates = defaultdict(set)
#     unaccommodated_students = []
    
#     with transaction.atomic():
#         pair_difficulties = [(i, max(conflict_scores[i])) for i in range(len(course_pairs))]
#         pair_difficulties.sort(key=lambda x: x[1], reverse=True)
        
#         slots_by_date = defaultdict(list)
#         for slot_idx, (date, label, start, end) in enumerate(date_slots):
#             slots_by_date[date].append(slot_idx)
        
#         assigned_slots = set()
        
#         for pair_idx, _ in pair_difficulties:
#             pair = course_pairs[pair_idx]
            
#             best_slot_idx = None
#             best_slot_score = float('inf')
            
#             sorted_dates = sorted(slots_by_date.keys())
            
#             for date in sorted_dates:
#                 slot_indices = slots_by_date[date]
                
#                 has_date_conflict = False
#                 for course_id in pair:
#                     student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
#                     for student_id in student_ids:
#                         if date in student_exam_dates[student_id]:
#                             has_date_conflict = True
#                             break
#                     if has_date_conflict:
#                         break
                
#                 if has_date_conflict:
#                     continue   
                
#                 for slot_idx in slot_indices:
#                     if slot_idx in assigned_slots:
#                         continue
                    
#                     if conflict_scores[pair_idx][slot_idx] < best_slot_score:
#                         best_slot_idx = slot_idx
#                         best_slot_score = conflict_scores[pair_idx][slot_idx]
                
#                 if best_slot_idx is not None:
#                     break
            
#             if best_slot_idx is None:
#                 raise ValueError("Cannot find suitable slot for all course pairs while maintaining schedule constraints.")
            
#             assigned_slots.add(best_slot_idx)
#             exam_date, label, start_time, end_time = date_slots[best_slot_idx]
            
#             pair_exams = []
#             for course_id in pair:
#                 course = Course.objects.get(id=course_id)
                
#                 exam = Exam.objects.create(
#                     course=course,
#                     date=exam_date,
#                     start_time=start_time,
#                     end_time=end_time
#                 )
#                 exams_created.append(exam)
#                 pair_exams.append(exam)
                
#                 students = Enrollment.objects.filter(course=course)
#                 for enrollment in students:
#                     student_exam_dates[enrollment.student_id].add(exam_date)
            
#             unaccommodated = allocate_shared_rooms(pair_exams)
#             unaccommodated_students.extend(unaccommodated)
#     print(unaccommodated_students)
#     return exams_created, unaccommodated_students



# def allocate_shared_rooms(exams):
#     if not exams:
#         return []
        
#     rooms = list(Room.objects.order_by('-capacity'))
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     students_by_exam = {}
#     for exam in exams:
#         enrolled_students = list(Enrollment.objects.filter(course=exam.course).select_related('student'))
#         students_by_exam[exam.id] = enrolled_students
    
#     total_students = sum(len(students) for students in students_by_exam.values())
#     total_capacity = sum(room.capacity for room in rooms)
    
#     unaccommodated_students = []
    
#     if total_students > total_capacity:
#         for exam_id, students in students_by_exam.items():
#             proportion = len(students) / total_students
#             max_accommodated = int(proportion * total_capacity)
#             if len(students) > max_accommodated:
#                 unaccommodated_students.extend([s.student for s in students[max_accommodated:]])
#                 students_by_exam[exam_id] = students[:max_accommodated]
    
#     all_student_exams = []
#     for exam in exams:
#         for enrollment in students_by_exam[exam.id]:
#             student_exam = StudentExam(student=enrollment.student, exam=exam)
#             all_student_exams.append(student_exam)
    
#     random.shuffle(all_student_exams)
    
#     current_room_index = 0
#     current_room_capacity = rooms[0].capacity if rooms else 0
    
#     for student_exam in all_student_exams:
#         if current_room_capacity <= 0:
#             current_room_index += 1
#             if current_room_index >= len(rooms):
#                 unaccommodated_students.append(student_exam.student)
#                 continue
#             current_room_capacity = rooms[current_room_index].capacity
        
#         student_exam.room = rooms[current_room_index]
#         current_room_capacity -= 1
    
#     StudentExam.objects.bulk_create(all_student_exams)
    
#     return unaccommodated_students


 

# def allocate_single_exam_rooms(exam):
#     """
#     Allocate students to rooms for a single exam
#     Returns a list of students who couldn't be accommodated
#     """
#     rooms = list(Room.objects.order_by('-capacity'))
    
#     if not rooms:
#         raise Exception("No rooms available for allocation.")
    
#     student_exam_qs = StudentExam.objects.filter(exam=exam).select_related('student')
#     unassigned = list(student_exam_qs)
    
#     # Shuffle students to prevent friends from sitting together
#     random.shuffle(unassigned)
    
#     total_students = len(unassigned)
#     available_capacity = sum(r.capacity for r in rooms)
#     unaccommodated_students = []
    
#     # Handle case where we don't have enough room capacity
#     if total_students > available_capacity:
#         accommodated_count = available_capacity
#         unaccommodated_students = [se.student for se in unassigned[accommodated_count:]]
#         unassigned = unassigned[:accommodated_count]
    
#     # Assign students to rooms
#     for room in rooms:
#         if not unassigned:
#             break
            
#         chunk = unassigned[:room.capacity]
#         for se in chunk:
#             se.room = room
#             se.save(update_fields=['room'])
            
#         unassigned = unassigned[room.capacity:]
    
#     return unaccommodated_students

# def cancel_exam(exam_id):
#     """
#     Cancel a scheduled exam
#     Returns True if successful
#     """
#     with transaction.atomic():
#         StudentExam.objects.filter(exam_id=exam_id).delete()
#         Exam.objects.filter(id=exam_id).delete()
    
#     return True

# def reschedule_exam(exam_id, new_date, slot=None):
#     """
#     Reschedule an exam to a new date and/or time with comprehensive validation
#     Checks ALL constraints: student conflicts, room capacity, Friday slots, etc.
#     Returns the updated exam instance
#     """
#     with transaction.atomic():
#         exam = Exam.objects.get(id=exam_id)
        
#         # Store original values for rollback if needed
#         original_date = exam.date
#         original_start_time = exam.start_time
#         original_end_time = exam.end_time
        
#         # 1. VALIDATE DAY OF WEEK
#         weekday = new_date.strftime('%A')
#         if weekday in NO_EXAM_DAYS:
#             raise ValueError(f"Cannot schedule an exam on {weekday}.")
        
#         # 2. VALIDATE AND SET TIME SLOT
#         new_start_time = exam.start_time  # Default to current time
#         new_end_time = exam.end_time
        
#         if slot:
#             # Friday slot validation
#             if weekday == 'Friday':
#                 available_slots = FRIDAY_SLOTS
#             else:
#                 available_slots = SLOTS
            
#             slot_match = next((s for s in available_slots if s[0].lower() == slot.lower()), None)
#             if not slot_match:
#                 available_slot_names = [s[0] for s in available_slots]
#                 raise ValueError(
#                     f"Invalid slot '{slot}' for {weekday}. "
#                     f"Available slots: {', '.join(available_slot_names)}"
#                 )
            
#             _, new_start_time, new_end_time = slot_match
#         else:
#             # If no slot specified, validate current time slot is valid for the new day
#             if weekday == 'Friday':
#                 # Check if current time slot is valid for Friday
#                 current_slot = (exam.start_time, exam.end_time)
#                 friday_times = [(start, end) for _, start, end in FRIDAY_SLOTS]
                
#                 if current_slot not in friday_times:
#                     available_slots = [f"{label} ({start}-{end})" for label, start, end in FRIDAY_SLOTS]
#                     raise ValueError(
#                         f"Current time slot is not valid for Friday. "
#                         f"Available Friday slots: {', '.join(available_slots)}. "
#                         f"Please specify a valid slot."
#                     )
        
#         # 3. CHECK STUDENT CONFLICTS
#         enrolled_students = Enrollment.objects.filter(course=exam.course)
#         conflicted_students = []
        
#         for enrollment in enrolled_students:
#             existing_exams = StudentExam.objects.filter(
#                 student=enrollment.student,
#                 exam__date=new_date
#             ).exclude(exam_id=exam_id)
            
#             if existing_exams.exists():
#                 conflicted_students.append({
#                     'student': enrollment.student.reg_no,
#                     'conflicting_exams': [se.exam.course.title for se in existing_exams]
#                 })
        
#         if conflicted_students:
#             conflict_details = []
#             for conflict in conflicted_students[:3]:   
#                 courses = ', '.join(conflict['conflicting_exams'])
#                 conflict_details.append(f"{conflict['student']} (conflicts with: {courses})")
            
#             error_msg = f"Student conflicts found: {'; '.join(conflict_details)}"
#             if len(conflicted_students) > 3:
#                 error_msg += f" ... and {len(conflicted_students) - 3} more students"
            
#             raise ValueError(error_msg)
        
#         # 4. CHECK ROOM CAPACITY CONFLICTS
#         # Get number of students for this exam
#         exam_student_count = Enrollment.objects.filter(course=exam.course).count()
        
#         # Check existing exams in the same time slot
#         existing_slot_exams = Exam.objects.filter(
#             date=new_date,
#             start_time=new_start_time,
#             end_time=new_end_time
#         ).exclude(id=exam_id)
        
#         # Calculate total students that would need accommodation in this slot
#         total_students_needed = exam_student_count
#         other_exams_students = 0
        
#         for other_exam in existing_slot_exams:
#             other_exam_students = Enrollment.objects.filter(course=other_exam.course).count()
#             other_exams_students += other_exam_students
#             total_students_needed += other_exam_students
        
#         # Check available room capacity
#         total_room_capacity = get_total_room_capacity()
        
#         if total_students_needed > total_room_capacity:
#             raise ValueError(
#                 f"Insufficient room capacity. Required: {total_students_needed} students, "
#                 f"Available: {total_room_capacity} seats. "
#                 f"This exam needs {exam_student_count} seats, "
#                 f"other exams in this slot need {other_exams_students} seats."
#             )
        
#         # 5. CHECK FOR COURSE COMPATIBILITY CONFLICTS
#         # Ensure courses scheduled together don't share students
#         if existing_slot_exams:
#             exam_students = set(
#                 Enrollment.objects.filter(course=exam.course)
#                 .values_list('student_id', flat=True)
#             )
            
#             for other_exam in existing_slot_exams:
#                 other_students = set(
#                     Enrollment.objects.filter(course=other_exam.course)
#                     .values_list('student_id', flat=True)
#                 )
                
#                 common_students = exam_students.intersection(other_students)
#                 if common_students:
#                     common_count = len(common_students)
#                     raise ValueError(
#                         f"Course compatibility conflict: {common_count} student(s) are enrolled in both "
#                         f"'{exam.course.name}' and '{other_exam.course.name}'. "
#                         f"These courses cannot be scheduled in the same time slot."
#                     )
        
#         # 6. VALIDATE ROOM ALLOCATION FEASIBILITY
#         # Check if we can actually allocate rooms for all courses in this slot
#         if existing_slot_exams:
#             # Simulate room allocation
#             all_slot_exams = list(existing_slot_exams) + [exam]
#             room_requirements = []
            
#             for slot_exam in all_slot_exams:
#                 student_count = Enrollment.objects.filter(course=slot_exam.course).count()
#                 room_requirements.append(student_count)
            
#             # Check if we can fit all exams in available rooms
#             rooms = list(Room.objects.order_by('-capacity'))
#             if not can_accommodate_exams(room_requirements, rooms):
#                 raise ValueError(
#                     f"Cannot allocate rooms efficiently for all exams in this slot. "
#                     f"Room allocation would fail with current room configuration."
#                 )
        
#         # 7. UPDATE EXAM AND HANDLE ROOM REALLOCATION
#         exam.date = new_date
#         exam.start_time = new_start_time
#         exam.end_time = new_end_time
#         exam.save()
        
#         # 8. REALLOCATE ROOMS FOR THIS TIME SLOT
#         # Get all exams in the new time slot (including the rescheduled one)
#         slot_exams = list(Exam.objects.filter(
#             date=new_date,
#             start_time=new_start_time,
#             end_time=new_end_time
#         ))
        
#         # Clear existing room assignments for this slot
#         StudentExam.objects.filter(exam__in=slot_exams).update(room=None)
        
#         # Reallocate rooms
#         try:
#             unaccommodated = allocate_shared_rooms(slot_exams)
#             if unaccommodated:
#                 # Rollback the exam changes
#                 exam.date = original_date
#                 exam.start_time = original_start_time
#                 exam.end_time = original_end_time
#                 exam.save()
                
#                 raise ValueError(
#                     f"Room allocation failed: {len(unaccommodated)} students could not be accommodated. "
#                     f"Exam rescheduling has been cancelled."
#                 )
#         except Exception as e:
#             # Rollback on any room allocation error
#             exam.date = original_date
#             exam.start_time = original_start_time
#             exam.end_time = original_end_time
#             exam.save()
#             raise ValueError(f"Room allocation error: {str(e)}")
    
#     return exam


# def can_accommodate_exams(student_counts, rooms):
#     """
#     Check if given student counts can be accommodated in available rooms
#     Uses a simple bin-packing approach
#     """
#     if not rooms:
#         return False
    
#     total_students = sum(student_counts)
#     total_capacity = sum(room.capacity for room in rooms)
    
#     if total_students > total_capacity:
#         return False
    
#     # Simple greedy allocation check
#     sorted_counts = sorted(student_counts, reverse=True)
#     sorted_rooms = sorted(rooms, key=lambda r: r.capacity, reverse=True)
    
#     # Try to fit largest student groups in largest rooms
#     room_remaining = [room.capacity for room in sorted_rooms]
    
#     for count in sorted_counts:
#         # Find a room that can accommodate this count
#         allocated = False
#         for i, remaining in enumerate(room_remaining):
#             if remaining >= count:
#                 room_remaining[i] -= count
#                 allocated = True
#                 break
        
#         if not allocated:
#             return False
    
#     return True


# def get_reschedule_suggestions(exam_id, preferred_date_range=7):
#     """
#     Get suggestions for rescheduling an exam
#     Returns available slots within the preferred date range
#     """
#     exam = Exam.objects.get(id=exam_id)
#     current_date = exam.date
    
#     # Look for available slots within the date range
#     start_search = current_date - timedelta(days=preferred_date_range)
#     end_search = current_date + timedelta(days=preferred_date_range)
    
#     suggestions = []
#     current = start_search
    
#     while current <= end_search:
#         if current == exam.date:
#             current += timedelta(days=1)
#             continue
            
#         weekday = current.strftime('%A')
#         if weekday in NO_EXAM_DAYS:
#             current += timedelta(days=1)
#             continue
        
#         # Get available slots for this day
#         available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
        
#         for slot_name, start_time, end_time in available_slots:
#             try:
#                 # Test if this slot would work (without actually rescheduling)
#                 test_conflicts = check_reschedule_feasibility(exam_id, current, slot_name)
#                 if not test_conflicts:
#                     suggestions.append({
#                         'date': current,
#                         'slot': slot_name,
#                         'start_time': start_time,
#                         'end_time': end_time,
#                         'weekday': weekday
#                     })
#             except:
#                 continue  # Skip this slot if it has issues
        
#         current += timedelta(days=1)
    
#     return suggestions


# def check_reschedule_feasibility(exam_id, new_date, slot_name):
#     """
#     Check if rescheduling is feasible without actually doing it
#     Returns list of conflicts/issues, empty list if feasible
#     """
#     conflicts = []
    
#     try:
#         exam = Exam.objects.get(id=exam_id)
#         weekday = new_date.strftime('%A')
        
#         # Check day validity
#         if weekday in NO_EXAM_DAYS:
#             conflicts.append(f"Cannot schedule on {weekday}")
#             return conflicts
        
#         # Check slot validity
#         available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
#         slot_match = next((s for s in available_slots if s[0].lower() == slot_name.lower()), None)
#         if not slot_match:
#             conflicts.append(f"Invalid slot '{slot_name}' for {weekday}")
#             return conflicts
        
#         _, new_start_time, new_end_time = slot_match
        
#         # Check student conflicts
#         enrolled_students = Enrollment.objects.filter(course=exam.course)
#         student_conflicts = 0
        
#         for enrollment in enrolled_students:
#             existing_exams = StudentExam.objects.filter(
#                 student=enrollment.student,
#                 exam__date=new_date
#             ).exclude(exam_id=exam_id)
            
#             if existing_exams.exists():
#                 student_conflicts += 1
        
#         if student_conflicts > 0:
#             conflicts.append(f"{student_conflicts} student conflicts")
        
#         # Check room capacity
#         exam_students = Enrollment.objects.filter(course=exam.course).count()
#         existing_slot_exams = Exam.objects.filter(
#             date=new_date,
#             start_time=new_start_time,
#             end_time=new_end_time
#         ).exclude(id=exam_id)
        
#         total_students = exam_students
#         for other_exam in existing_slot_exams:
#             total_students += Enrollment.objects.filter(course=other_exam.course).count()
        
#         total_capacity = get_total_room_capacity()
#         if total_students > total_capacity:
#             conflicts.append(f"Insufficient capacity ({total_students} needed, {total_capacity} available)")
        
#     except Exception as e:
#         conflicts.append(f"Error checking feasibility: {str(e)}")
    
#     return conflicts

# def get_unaccommodated_students():
#     """
#     Get a list of students who couldn't be accommodated in the exam schedule
#     """
#     # Students without a room assignment
#     unaccommodated = StudentExam.objects.filter(room__isnull=True).select_related('student', 'exam__course')
    
#     result = []
#     for student_exam in unaccommodated:
#         result.append({
#             'student': student_exam.student,
#             'course': student_exam.exam.course,
#             'exam_date': student_exam.exam.date,
#             'exam_slot': (student_exam.exam.start_time, student_exam.exam.end_time)
#         })
    
#     return result

# def find_optimal_exam_dates(start_date=None):
#     """
#     Find optimal dates for scheduling exams based on the course enrollment patterns
#     """
#     if not start_date:
#         start_date = now().date() + timedelta(days=1)
    
#     # Get course conflict matrix
#     conflict_matrix = analyze_student_course_conflicts()
    
#     # Find compatible course pairs
#     course_pairs = find_compatible_courses(conflict_matrix)
    
#     # Calculate the minimum number of days needed
#     min_days_needed = len(course_pairs) // 3  # 3 slots per day
#     if len(course_pairs) % 3 > 0:
#         min_days_needed += 1
    
#     # Generate enough slots
#     date_slots = get_exam_slots(start_date, max_slots=min_days_needed * 3 + 5)  # Add buffer
    
#     return {
#         'start_date': start_date,
#         'suggested_end_date': start_date + timedelta(days=min_days_needed + 2),  # Add buffer
#         'min_days_needed': min_days_needed,
#         'course_pairs': course_pairs,
#         'available_slots': date_slots[:min_days_needed * 3]
#     }

# def verify_exam_schedule():
#     """
#     Verify that the current exam schedule has no conflicts
#     Returns a list of any conflicts found
#     """
#     conflicts = []
    
#     # Check for students with multiple exams in one day
#     student_exams = defaultdict(list)
#     for student_exam in StudentExam.objects.select_related('student', 'exam'):
#         student_exams[student_exam.student.id].append(student_exam)
    
#     for student_id, exams in student_exams.items():
#         exams_by_date = defaultdict(list)
#         for exam in exams:
#             exams_by_date[exam.exam.date].append(exam)
        
#         for date, day_exams in exams_by_date.items():
#             if len(day_exams) > 1:
#                 conflicts.append({
#                     'type': 'multiple_exams_per_day',
#                     'student_id': student_id,
#                     'date': date,
#                     'exams': [e.exam.id for e in day_exams]
#                 })
    
#     # Check for room overallocation
#     exams_by_slot = defaultdict(list)
#     for exam in Exam.objects.all():
#         slot_key = (exam.date, exam.start_time, exam.end_time)
#         exams_by_slot[slot_key].append(exam)
    
#     for slot, slot_exams in exams_by_slot.items():
#         room_student_counts = defaultdict(lambda: defaultdict(int))
        
#         for exam in slot_exams:
#             student_exams = StudentExam.objects.filter(exam=exam).select_related('room')
#             for se in student_exams:
#                 if se.room:
#                     room_student_counts[se.room.id][exam.id] += 1
        
#         for room_id, exam_counts in room_student_counts.items():
#             room = Room.objects.get(id=room_id)
#             total_students = sum(exam_counts.values())
            
#             if total_students > room.capacity:
#                 conflicts.append({
#                     'type': 'room_overallocation',
#                     'room_id': room_id,
#                     'capacity': room.capacity,
#                     'allocated': total_students,
#                     'slot': slot,
#                     'exams': list(exam_counts.keys())
#                 })
    
#     # Check for courses in same slot without being in same group
#     # (they shouldn't share any students)
#     exams_by_slot = defaultdict(list)
#     for exam in Exam.objects.all():
#         slot_key = (exam.date, exam.start_time, exam.end_time)
#         exams_by_slot[slot_key].append(exam)
    
#     for slot, slot_exams in exams_by_slot.items():
#         # Skip slots with only one exam
#         if len(slot_exams) < 2:
#             continue
            
#         # For each pair of exams in this slot, check if they share students
#         for i, exam1 in enumerate(slot_exams):
#             for exam2 in slot_exams[i+1:]:
#                 # Check if these exams share any students
#                 students1 = set(Enrollment.objects.filter(course=exam1.course).values_list('student_id', flat=True))
#                 students2 = set(Enrollment.objects.filter(course=exam2.course).values_list('student_id', flat=True))
                
#                 common_students = students1.intersection(students2)
#                 if common_students:
#                     conflicts.append({
#                         'type': 'student_exam_conflict',
#                         'course1': exam1.course.id,
#                         'course2': exam2.course.id,
#                         'common_students': list(common_students),
#                         'slot': slot
#                     })
    
#     return conflicts


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

def can_pair_by_semester(course1_id, course2_id):
    """
    Check if two courses can be paired based on semester rules:
    - Cannot pair adjacent semesters (e.g., Semester 1 with 2, or 2 with 3)
    - Need at least one semester gap
    """
    try:
        course1 = Course.objects.get(id=course1_id)
        course2 = Course.objects.get(id=course2_id)
        
        # Assuming courses have a 'semester' field
        # If not, you might need to adjust this based on your Course model
        semester1 = getattr(course1, 'semester', 1)
        semester2 = getattr(course2, 'semester', 1)
        
        # Calculate semester gap
        semester_gap = abs(semester1 - semester2)
        
        # Must have at least one semester gap (difference >= 2)
        return semester_gap >= 2
        
    except Course.DoesNotExist:
        return False

def find_compatible_courses(course_conflict_matrix):
    """
    Group courses into compatible groups for room sharing
    Now considers semester pairing rules alongside student conflicts
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
    
    # Build compatibility graph considering both student conflicts and semester rules
    compatibility_graph = {course: set() for course in all_courses}
    
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                
                # Check student conflicts
                has_student_conflict = pair in course_conflict_matrix and course_conflict_matrix[pair] > 0
                
                # Check semester compatibility
                semester_compatible = can_pair_by_semester(course1, course2)
                
                # Courses are compatible if they have no student conflicts AND satisfy semester rules
                if not has_student_conflict and semester_compatible:
                    compatibility_graph[course1].add(course2)
    
    # Group compatible courses - now limited to pairs for room sharing
    remaining_courses = set(all_courses)
    course_groups = []
    
    while remaining_courses:
        # Start a new group with maximum 2 courses for room sharing
        course_group = []
        
        if remaining_courses:
            # Pick a course with the fewest compatible options (hardest to place)
            course1 = min(
                remaining_courses,
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
            )
            
            course_group.append(course1)
            remaining_courses.remove(course1)
            
            # Find exactly one compatible course to pair with
            compatible_with_course1 = set(compatibility_graph[course1]) & remaining_courses
            
            if compatible_with_course1:
                # Select the course with fewest remaining compatible options
                course2 = min(
                    compatible_with_course1,
                    key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
                )
                course_group.append(course2)
                remaining_courses.remove(course2)
        
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

def detect_scheduling_conflicts_with_day_gap(course_pairs, student_assignments, date_slots):
    """
    Detect scheduling conflicts including the mandatory day-off rule
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
    
    # Calculate conflicts considering day-gap rule
    for student_id, assignments in student_assignments.items():
        # For each pair of assignments for this student
        for i, (pair_idx1, course_id1) in enumerate(assignments):
            for j, (pair_idx2, course_id2) in enumerate(assignments):
                if i >= j:  # Avoid double counting
                    continue
                
                # These two course pairs need day-gap enforcement
                for slot_idx1, (date1, _, _, _) in enumerate(date_slots):
                    for slot_idx2, (date2, _, _, _) in enumerate(date_slots):
                        day_gap = abs((date2 - date1).days)
                        
                        # Violation: same day or consecutive days
                        if day_gap <= 1:
                            conflict_scores[pair_idx1][slot_idx1] += 10  # High penalty
                            conflict_scores[pair_idx2][slot_idx2] += 10
                        # Preference: at least 2 days gap
                        elif day_gap == 2:
                            conflict_scores[pair_idx1][slot_idx1] += 2  # Medium penalty
                            conflict_scores[pair_idx2][slot_idx2] += 2
    
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

def allocate_rooms_with_pairing_rules(exams):
    """
    Allocate students to rooms following the new room usage policy:
    - Each room hosts exactly 2 exams per slot by default
    - Capacity divided equally between courses
    - Fallback to more than 2 exams only if necessary
    """
    if not exams:
        return []
    
    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    # Group exams by compatible pairs (already done in course grouping)
    # Since we're grouping compatible courses, exams should come in pairs
    
    students_by_exam = {}
    total_students = 0
    
    for exam in exams:
        enrolled_students = list(Enrollment.objects.filter(course=exam.course).select_related('student'))
        students_by_exam[exam.id] = enrolled_students
        total_students += len(enrolled_students)
    
    total_capacity = sum(room.capacity for room in rooms)
    unaccommodated_students = []
    
    # Check if we can accommodate all students
    if total_students > total_capacity:
        # Calculate proportional reduction
        for exam_id, students in students_by_exam.items():
            proportion = len(students) / total_students
            max_accommodated = int(proportion * total_capacity)
            if len(students) > max_accommodated:
                unaccommodated_students.extend([s.student for s in students[max_accommodated:]])
                students_by_exam[exam_id] = students[:max_accommodated]
    
    # Allocate rooms following the 2-exams-per-room rule
    room_assignments = []
    exam_list = list(exams)
    
    # Process exams in pairs
    for i in range(0, len(exam_list), 2):
        exam_pair = exam_list[i:i+2]
        
        if len(exam_pair) == 2:
            # Standard case: 2 exams per room
            exam1, exam2 = exam_pair
            students1 = students_by_exam[exam1.id]
            students2 = students_by_exam[exam2.id]
            
            total_pair_students = len(students1) + len(students2)
            
            # Find a room that can accommodate both exams
            suitable_room = None
            for room in rooms:
                if room.capacity >= total_pair_students:
                    suitable_room = room
                    rooms.remove(room)  # Remove from available rooms
                    break
            
            if suitable_room:
                # Divide capacity equally
                capacity_per_exam = suitable_room.capacity // 2
                
                # Allocate students to the room
                for enrollment in students1[:capacity_per_exam]:
                    student_exam = StudentExam(
                        student=enrollment.student,
                        exam=exam1,
                        room=suitable_room
                    )
                    room_assignments.append(student_exam)
                
                for enrollment in students2[:capacity_per_exam]:
                    student_exam = StudentExam(
                        student=enrollment.student,
                        exam=exam2,
                        room=suitable_room
                    )
                    room_assignments.append(student_exam)
                
                # Handle overflow students
                overflow1 = students1[capacity_per_exam:]
                overflow2 = students2[capacity_per_exam:]
                
                for student in overflow1:
                    unaccommodated_students.append(student.student)
                for student in overflow2:
                    unaccommodated_students.append(student.student)
            else:
                # Fallback: distribute across multiple rooms
                all_students = [(s, exam1) for s in students1] + [(s, exam2) for s in students2]
                random.shuffle(all_students)
                
                for enrollment, exam in all_students:
                    allocated = False
                    for room in rooms:
                        current_occupancy = sum(1 for sa in room_assignments if sa.room == room)
                        if current_occupancy < room.capacity:
                            student_exam = StudentExam(
                                student=enrollment.student,
                                exam=exam,
                                room=room
                            )
                            room_assignments.append(student_exam)
                            allocated = True
                            break
                    
                    if not allocated:
                        unaccommodated_students.append(enrollment.student)
        else:
            # Single exam case
            exam = exam_pair[0]
            students = students_by_exam[exam.id]
            
            # Find a room for the single exam
            suitable_room = None
            for room in rooms:
                if room.capacity >= len(students):
                    suitable_room = room
                    rooms.remove(room)
                    break
            
            if suitable_room:
                for enrollment in students:
                    student_exam = StudentExam(
                        student=enrollment.student,
                        exam=exam,
                        room=suitable_room
                    )
                    room_assignments.append(student_exam)
            else:
                # Distribute across available rooms
                for enrollment in students:
                    allocated = False
                    for room in rooms:
                        current_occupancy = sum(1 for sa in room_assignments if sa.room == room)
                        if current_occupancy < room.capacity:
                            student_exam = StudentExam(
                                student=enrollment.student,
                                exam=exam,
                                room=room
                            )
                            room_assignments.append(student_exam)
                            allocated = True
                            break
                    
                    if not allocated:
                        unaccommodated_students.append(enrollment.student)
    
    # Bulk create all student exam assignments
    StudentExam.objects.bulk_create(room_assignments)
    
    return unaccommodated_students

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Generate exam schedule with enhanced rules:
    1. Mandatory day-off between student exams
    2. Room usage policy (2 exams per room)
    3. Semester-aware exam pairing
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
    
    # Generate more slots to accommodate day-gap requirements
    date_slots = get_exam_slots(start_date, max_slots=len(course_pairs) * 5)
    
    student_assignments = student_course_assignment(course_pairs)
    conflict_scores = detect_scheduling_conflicts_with_day_gap(course_pairs, student_assignments, date_slots)
    
    exams_created = []
    student_exam_dates = defaultdict(set)
    unaccommodated_students = []
    
    with transaction.atomic():
        # Sort pairs by difficulty (those with higher conflict scores first)
        pair_difficulties = [(i, max(conflict_scores[i])) for i in range(len(course_pairs))]
        pair_difficulties.sort(key=lambda x: x[1], reverse=True)
        
        slots_by_date = defaultdict(list)
        for slot_idx, (date, label, start, end) in enumerate(date_slots):
            slots_by_date[date].append(slot_idx)
        
        assigned_slots = set()
        
        for pair_idx, _ in pair_difficulties:
            pair = course_pairs[pair_idx]
            
            best_slot_idx = None
            best_slot_score = float('inf')
            
            sorted_dates = sorted(slots_by_date.keys())
            
            for date in sorted_dates:
                slot_indices = slots_by_date[date]
                
                # Check day-gap conflicts
                has_day_gap_conflict = False
                for course_id in pair:
                    student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
                    for student_id in student_ids:
                        # Check if student has exams on adjacent days
                        for existing_date in student_exam_dates[student_id]:
                            day_gap = abs((date - existing_date).days)
                            if day_gap <= 1:  # Same day or consecutive days
                                has_day_gap_conflict = True
                                break
                        if has_day_gap_conflict:
                            break
                    if has_day_gap_conflict:
                        break
                
                if has_day_gap_conflict:
                    continue
                
                for slot_idx in slot_indices:
                    if slot_idx in assigned_slots:
                        continue
                    
                    if conflict_scores[pair_idx][slot_idx] < best_slot_score:
                        best_slot_idx = slot_idx
                        best_slot_score = conflict_scores[pair_idx][slot_idx]
                
                if best_slot_idx is not None:
                    break
            
            if best_slot_idx is None:
                raise ValueError("Cannot find suitable slot for all course pairs while maintaining day-gap constraints.")
            
            assigned_slots.add(best_slot_idx)
            exam_date, label, start_time, end_time = date_slots[best_slot_idx]
            
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
                
                students = Enrollment.objects.filter(course=course)
                for enrollment in students:
                    student_exam_dates[enrollment.student_id].add(exam_date)
            
            # Use the new room allocation function
            unaccommodated = allocate_rooms_with_pairing_rules(pair_exams)
            unaccommodated_students.extend(unaccommodated)
    
    print(f"Unaccommodated students: {len(unaccommodated_students)}")
    return exams_created, unaccommodated_students

def verify_enhanced_exam_schedule():
    """
    Verify that the current exam schedule follows all enhanced rules
    """
    conflicts = []
    
    # 1. Check mandatory day-off rule
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exams[student_exam.student.id].append(student_exam)
    
    for student_id, exams in student_exams.items():
        exam_dates = sorted([exam.exam.date for exam in exams])
        
        for i in range(len(exam_dates) - 1):
            day_gap = (exam_dates[i + 1] - exam_dates[i]).days
            if day_gap <= 1:
                conflicts.append({
                    'type': 'day_gap_violation',
                    'student_id': student_id,
                    'dates': [exam_dates[i], exam_dates[i + 1]],
                    'gap_days': day_gap
                })
    
    # 2. Check room usage policy
    room_usage = defaultdict(lambda: defaultdict(int))
    for student_exam in StudentExam.objects.select_related('exam', 'room'):
        if student_exam.room:
            slot_key = (student_exam.exam.date, student_exam.exam.start_time, student_exam.exam.end_time)
            room_usage[student_exam.room.id][slot_key] += 1
    
    for room_id, slots in room_usage.items():
        for slot, count in slots.items():
            # Check if room is being used efficiently
            room = Room.objects.get(id=room_id)
            efficiency = count / room.capacity
            
            if efficiency < 0.5:  # Less than 50% utilization
                conflicts.append({
                    'type': 'room_underutilization',
                    'room_id': room_id,
                    'slot': slot,
                    'utilization': efficiency
                })
    
    # 3. Check semester pairing rules
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.select_related('course'):
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)
    
    for slot, slot_exams in exams_by_slot.items():
        if len(slot_exams) >= 2:
            for i, exam1 in enumerate(slot_exams):
                for exam2 in slot_exams[i+1:]:
                    if not can_pair_by_semester(exam1.course.id, exam2.course.id):
                        conflicts.append({
                            'type': 'semester_pairing_violation',
                            'course1': exam1.course.id,
                            'course2': exam2.course.id,
                            'slot': slot,
                            'semester1': getattr(exam1.course, 'semester', 'N/A'),
                            'semester2': getattr(exam2.course, 'semester', 'N/A')
                        })
    
    return conflicts

# Update the remaining functions to work with the new rules
def reschedule_exam(exam_id, new_date, slot=None):
    """
    Enhanced reschedule function that considers day-gap and room pairing rules
    """
    with transaction.atomic():
        exam = Exam.objects.get(id=exam_id)
        
        # Store original values
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
                raise ValueError(f"Invalid slot '{slot}' for {weekday}. Available slots: {', '.join(available_slot_names)}")
            
            _, new_start_time, new_end_time = slot_match
        
        # Check day-gap constraints
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        day_gap_violations = []
        
        for enrollment in enrolled_students:
            other_exams = StudentExam.objects.filter(student=enrollment.student).exclude(exam_id=exam_id)
            
            for other_exam in other_exams:
                day_gap = abs((new_date - other_exam.exam.date).days)
                if day_gap <= 1:
                    day_gap_violations.append({
                        'student': enrollment.student.reg_no,
                        'other_exam_date': other_exam.exam.date,
                        'gap_days': day_gap
                    })
        
        if day_gap_violations:
            violation_details = []
            for violation in day_gap_violations[:3]:
                violation_details.append(f"{violation['student']} (gap: {violation['gap_days']} days)")
            
            error_msg = f"Day-gap violations found: {'; '.join(violation_details)}"
            if len(day_gap_violations) > 3:
                error_msg += f" ... and {len(day_gap_violations) - 3} more violations"
            
            raise ValueError(error_msg)
        
        # Check semester pairing rules for exams in the same slot
        existing_slot_exams = Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ).exclude(id=exam_id)
        
        for other_exam in existing_slot_exams:
            if not can_pair_by_semester(exam.course.id, other_exam.course.id):
                raise ValueError(
                    f"Semester pairing violation: Cannot pair {exam.course.name} "
                    f"with {other_exam.course.name} due to adjacent semester rule."
                )
        
        # Proceed with the reschedule
        exam.date = new_date
        exam.start_time = new_start_time
        exam.end_time = new_end_time
        exam.save()
        
        # Reallocate rooms for the entire slot
        slot_exams = list(Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ))
        
        StudentExam.objects.filter(exam__in=slot_exams).update(room=None)
        
        try:
            unaccommodated = allocate_rooms_with_pairing_rules(slot_exams)
            if unaccommodated:
                # Rollback
                exam.date = original_date
                exam.start_time = original_start_time
                exam.end_time = original_end_time
                exam.save()
                
                raise ValueError(f"Room allocation failed: {len(unaccommodated)} students could not be accommodated.")
        except Exception as e:
            # Rollback
            exam.date = original_date
            exam.start_time = original_start_time
            exam.end_time = original_end_time
            exam.save()
            raise ValueError(f"Room allocation error: {str(e)}")
    
    return exam

# Keep the remaining utility functions unchanged
def get_unaccommodated_students():
    """Get a list of students who couldn't be accommodated in the exam schedule"""
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

def check_reschedule_feasibility(exam_id, new_date, slot_name):
    """Check if rescheduling is feasible with enhanced rules"""
    conflicts = []
    
    try:
        exam = Exam.objects.get(id=exam_id)
        weekday = new_date.strftime('%A')
        
        if weekday in NO_EXAM_DAYS:
            conflicts.append(f"Cannot schedule on {weekday}")
            return conflicts
        
        # Check day-gap constraints
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        day_gap_conflicts = 0
        
        for enrollment in enrolled_students:
            other_exams = StudentExam.objects.filter(student=enrollment.student).exclude(exam_id=exam_id)
            
            for other_exam in other_exams:
                day_gap = abs((new_date - other_exam.exam.date).days)
                if day_gap <= 1:
                    day_gap_conflicts += 1
        
        if day_gap_conflicts > 0:
            conflicts.append(f"{day_gap_conflicts} day-gap violations")
        
        # Check semester pairing
        available_slots = FRIDAY_SLOTS if weekday == 'Friday' else SLOTS
        slot_match = next((s for s in available_slots if s[0].lower() == slot_name.lower()), None)
        if slot_match:
            _, new_start_time, new_end_time = slot_match
            
            existing_slot_exams = Exam.objects.filter(
                date=new_date,
                start_time=new_start_time,
                end_time=new_end_time
            ).exclude(id=exam_id)
            
            for other_exam in existing_slot_exams:
                if not can_pair_by_semester(exam.course.id, other_exam.course.id):
                    conflicts.append(f"Semester pairing violation with {other_exam.course.name}")
        
    except Exception as e:
        conflicts.append(f"Error checking feasibility: {str(e)}")
    
    return conflicts