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
# FRIDAY_SLOTS = [SLOTS[0:1]]   
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
FRIDAY_SLOTS = [SLOTS[0:1]]   
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

def check_semester_compatibility(course1_id, course2_id):
    """
    Check if two courses can be scheduled together based on semester compatibility.
    Courses from adjacent semesters (diff = 1) cannot be paired together.
    """
    try:
        course1 = Course.objects.get(id=course1_id)
        course2 = Course.objects.get(id=course2_id)
        
        # Get semester numbers (assuming courses have a semester field)
        semester1 = getattr(course1, 'semester', 1)
        semester2 = getattr(course2, 'semester', 1)
        
        # Courses from adjacent semesters cannot be paired
        semester_diff = abs(semester1 - semester2)
        return semester_diff != 1
    except:
        # If semester info is not available, assume compatible
        return True

def find_compatible_courses(course_conflict_matrix):
    """
    Group courses into compatible groups that can be scheduled together.
    Enhanced to limit to 2 courses per group and check semester compatibility.
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
    
    # Build compatibility graph considering both student conflicts and semester compatibility
    compatibility_graph = {course: set() for course in all_courses}
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                
                # Check student conflicts
                has_student_conflict = pair in course_conflict_matrix and course_conflict_matrix[pair] > 0
                
                # Check semester compatibility
                is_semester_compatible = check_semester_compatibility(course1, course2)
                
                # Courses are compatible if they don't share students AND are semester-compatible
                if not has_student_conflict and is_semester_compatible:
                    compatibility_graph[course1].add(course2)
    
    # Group compatible courses with maximum 2 courses per group
    remaining_courses = set(all_courses)
    course_groups = []
    
    while remaining_courses:
        # Start a new group
        course_group = []
        
        # Pick a course with the fewest compatible options (hardest to place)
        if remaining_courses:
            course1 = min(
                remaining_courses,
                key=lambda c: len([rc for rc in compatibility_graph[c] if rc in remaining_courses])
            )
            
            course_group.append(course1)
            remaining_courses.remove(course1)
            
            # Find one compatible course to pair with (limit to 2 per group)
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

def generate_exam_schedule(start_date=None, course_ids=None, semester=None):
    """
    Enhanced exam scheduling with one-day gap between student exams and improved room allocation
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
    
    # Generate more slots to account for one-day gaps
    date_slots = get_exam_slots(start_date, max_slots=len(course_pairs) * 6)  
    
    student_assignments = student_course_assignment(course_pairs)
    conflict_scores = detect_scheduling_conflicts(course_pairs, student_assignments, date_slots)
    
    exams_created = []
    student_exam_dates = defaultdict(set)  # Track exam dates for each student
    unaccommodated_students = []
    
    with transaction.atomic():
        # Sort pairs by difficulty (most constrained first)
        pair_difficulties = [(i, max(conflict_scores[i])) for i in range(len(course_pairs))]
        pair_difficulties.sort(key=lambda x: x[1], reverse=True)
        
        # Group slots by date for easier processing
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
                
                # Check if any student has exam conflicts with one-day gap rule
                has_conflict = False
                for course_id in pair:
                    student_ids = Enrollment.objects.filter(course_id=course_id).values_list('student_id', flat=True)
                    for student_id in student_ids:
                        # Check if student has exam on this date or adjacent dates
                        conflict_dates = {
                            date,  # Same day
                            date - timedelta(days=1),  # Previous day
                            date + timedelta(days=1),  # Next day
                        }
                        
                        if student_exam_dates[student_id] & conflict_dates:
                            has_conflict = True
                            break
                    if has_conflict:
                        break
                
                if has_conflict:
                    continue
                
                # Find best slot on this date
                for slot_idx in slot_indices:
                    if slot_idx in assigned_slots:
                        continue
                    
                    if conflict_scores[pair_idx][slot_idx] < best_slot_score:
                        best_slot_idx = slot_idx
                        best_slot_score = conflict_scores[pair_idx][slot_idx]
                
                if best_slot_idx is not None:
                    break
            
            if best_slot_idx is None:
                raise ValueError("Cannot find suitable slot for all course pairs while maintaining schedule constraints.")
            
            assigned_slots.add(best_slot_idx)
            exam_date, label, start_time, end_time = date_slots[best_slot_idx]
            
            # Create exams for this pair
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
                
                # Update student exam dates
                students = Enrollment.objects.filter(course=course)
                for enrollment in students:
                    student_exam_dates[enrollment.student_id].add(exam_date)
            
            # Allocate rooms with enhanced logic
            unaccommodated = allocate_shared_rooms_enhanced(pair_exams)
            unaccommodated_students.extend(unaccommodated)
    
    print(f"Unaccommodated students: {len(unaccommodated_students)}")
    return exams_created, unaccommodated_students

def allocate_shared_rooms_enhanced(exams):
    """
    Enhanced room allocation that prioritizes 2 exams per room and distributes fairly
    """
    if not exams:
        return []
    
    # Get all available rooms sorted by capacity (largest first)
    rooms = list(Room.objects.order_by('-capacity'))
    if not rooms:
        raise Exception("No rooms available for allocation.")
    
    # Calculate students per exam
    students_by_exam = {}
    total_students = 0
    for exam in exams:
        enrolled_students = list(Enrollment.objects.filter(course=exam.course).select_related('student'))
        students_by_exam[exam.id] = enrolled_students
        total_students += len(enrolled_students)
    
    total_room_capacity = sum(room.capacity for room in rooms)
    unaccommodated_students = []
    
    # Handle capacity shortage
    if total_students > total_room_capacity:
        shortage = total_students - total_room_capacity
        # Proportionally reduce students from each exam
        for exam_id, students in students_by_exam.items():
            if shortage <= 0:
                break
            exam_reduction = min(shortage, len(students) // 4)  # Reduce by up to 25%
            if exam_reduction > 0:
                unaccommodated_students.extend([s.student for s in students[-exam_reduction:]])
                students_by_exam[exam_id] = students[:-exam_reduction]
                shortage -= exam_reduction
    
    # Room allocation strategy: Try to assign 2 exams per room when possible
    room_assignments = []
    available_rooms = rooms.copy()
    
    # If we have exactly 2 exams, assign them to the same room if capacity allows
    if len(exams) == 2:
        total_needed = sum(len(students_by_exam[exam.id]) for exam in exams)
        suitable_room = None
        
        for room in available_rooms:
            if room.capacity >= total_needed:
                suitable_room = room
                break
        
        if suitable_room:
            room_assignments.append({
                'room': suitable_room,
                'exams': exams,
                'capacity_used': total_needed
            })
            available_rooms.remove(suitable_room)
        else:
            # Assign to separate rooms
            for exam in exams:
                exam_students = len(students_by_exam[exam.id])
                for room in available_rooms:
                    if room.capacity >= exam_students:
                        room_assignments.append({
                            'room': room,
                            'exams': [exam],
                            'capacity_used': exam_students
                        })
                        available_rooms.remove(room)
                        break
    
    # For single exam or when rooms are full
    if not room_assignments:
        for exam in exams:
            exam_students = len(students_by_exam[exam.id])
            assigned = False
            
            # Try to find a room with exactly enough capacity or reasonable excess
            for room in available_rooms:
                if room.capacity >= exam_students:
                    room_assignments.append({
                        'room': room,
                        'exams': [exam],
                        'capacity_used': exam_students
                    })
                    available_rooms.remove(room)
                    assigned = True
                    break
            
            if not assigned:
                # Emergency: use any available room even if overcrowded
                if available_rooms:
                    room = available_rooms[0]
                    room_assignments.append({
                        'room': room,
                        'exams': [exam],
                        'capacity_used': exam_students
                    })
                    available_rooms.remove(room)
                else:
                    # No rooms left, add all students to unaccommodated
                    unaccommodated_students.extend([s.student for s in students_by_exam[exam.id]])
    
    # Create StudentExam records
    all_student_exams = []
    for assignment in room_assignments:
        room = assignment['room']
        assigned_exams = assignment['exams']
        
        for exam in assigned_exams:
            for enrollment in students_by_exam[exam.id]:
                student_exam = StudentExam(
                    student=enrollment.student,
                    exam=exam,
                    room=room
                )
                all_student_exams.append(student_exam)
    
    # Shuffle to prevent clustering of students from same course
    random.shuffle(all_student_exams)
    
    # Batch create all student exam records
    StudentExam.objects.bulk_create(all_student_exams)
    
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
    Enhanced to respect one-day gap rule
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
        
        # 3. CHECK ONE-DAY GAP RULE
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        conflicted_students = []
        
        for enrollment in enrolled_students:
            # Check for exams on same day, previous day, and next day
            conflict_dates = [
                new_date - timedelta(days=1),
                new_date,
                new_date + timedelta(days=1)
            ]
            
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student,
                exam__date__in=conflict_dates
            ).exclude(exam_id=exam_id)
            
            if existing_exams.exists():
                conflicted_students.append({
                    'student': enrollment.student.reg_no,
                    'conflicting_exams': [
                        f"{se.exam.course.title} on {se.exam.date}" 
                        for se in existing_exams
                    ]
                })
        
        if conflicted_students:
            conflict_details = []
            for conflict in conflicted_students[:3]:
                courses = ', '.join(conflict['conflicting_exams'])
                conflict_details.append(f"{conflict['student']} (conflicts with: {courses})")
            
            error_msg = f"One-day gap rule violated: {'; '.join(conflict_details)}"
            if len(conflicted_students) > 3:
                error_msg += f" ... and {len(conflicted_students) - 3} more students"
            
            raise ValueError(error_msg)
        
        # 4. CHECK ROOM CAPACITY AND OTHER CONSTRAINTS
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
        
        # 5. CHECK SEMESTER COMPATIBILITY
        if existing_slot_exams:
            for other_exam in existing_slot_exams:
                if not check_semester_compatibility(exam.course.id, other_exam.course.id):
                    raise ValueError(
                        f"Semester compatibility conflict: Cannot schedule {exam.course.name} "
                        f"with {other_exam.course.name} (adjacent semesters)."
                    )
        
        # 6. UPDATE EXAM AND REALLOCATE ROOMS
        exam.date = new_date
        exam.start_time = new_start_time
        exam.end_time = new_end_time
        exam.save()
        
        # Reallocate rooms for the entire time slot
        slot_exams = list(Exam.objects.filter(
            date=new_date,
            start_time=new_start_time,
            end_time=new_end_time
        ))
        
        StudentExam.objects.filter(exam__in=slot_exams).update(room=None)
        
        try:
            unaccommodated = allocate_shared_rooms_enhanced(slot_exams)
            if unaccommodated:
                # Rollback
                exam.date = original_date
                exam.start_time = original_start_time
                exam.end_time = original_end_time
                exam.save()
                
                raise ValueError(
                    f"Room allocation failed: {len(unaccommodated)} students could not be accommodated."
                )
        except Exception as e:
            # Rollback
            exam.date = original_date
            exam.start_time = original_start_time
            exam.end_time = original_end_time
            exam.save()
            raise ValueError(f"Room allocation error: {str(e)}")
    
    return exam

def verify_exam_schedule():
    """
    Enhanced schedule verification including one-day gap rule
    """
    conflicts = []
    
    # Check one-day gap rule
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exams[student_exam.student.id].append(student_exam)
    
    for student_id, exams in student_exams.items():
        exam_dates = [exam.exam.date for exam in exams]
        exam_dates.sort()
        
        for i in range(len(exam_dates) - 1):
            date_diff = (exam_dates[i + 1] - exam_dates[i]).days
            if date_diff < 2:  # Less than 2 days apart (violates one-day gap)
                conflicts.append({
                    'type': 'one_day_gap_violation',
                    'student_id': student_id,
                    'date1': exam_dates[i],
                    'date2': exam_dates[i + 1],
                    'gap_days': date_diff
                })
    
    # Check room allocation (max 2 exams per room preference)
    room_usage = defaultdict(lambda: defaultdict(int))
    for student_exam in StudentExam.objects.select_related('exam', 'room'):
        if student_exam.room:
            slot_key = (student_exam.exam.date, student_exam.exam.start_time)
            room_usage[student_exam.room.id][slot_key] += 1
    
    for room_id, slot_usage in room_usage.items():
        for slot_key, exam_count in slot_usage.items():
            # Count unique exams in this room/slot
            unique_exams = StudentExam.objects.filter(
                room_id=room_id,
                exam__date=slot_key[0],
                exam__start_time=slot_key[1]
            ).values('exam_id').distinct().count()
            
            if unique_exams > 2:
                conflicts.append({
                    'type': 'room_exam_limit_exceeded',
                    'room_id': room_id,
                    'slot': slot_key,
                    'exam_count': unique_exams,
                    'recommended_max': 2
                })
    
    # Check semester compatibility
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.all():
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)
    
    for slot, slot_exams in exams_by_slot.items():
        if len(slot_exams) >= 2:
            for i, exam1 in enumerate(slot_exams):
                for exam2 in slot_exams[i+1:]:
                    if not check_semester_compatibility(exam1.course.id, exam2.course.id):
                        conflicts.append({
                            'type': 'semester_compatibility_conflict',
                            'course1': exam1.course.id,
                            'course2': exam2.course.id,
                            'slot': slot
                        })
    
    return conflicts

def get_schedule_statistics():
    """
    Get detailed statistics about the current exam schedule
    """
    total_exams = Exam.objects.count()
    total_students = StudentExam.objects.count()
    unaccommodated = StudentExam.objects.filter(room__isnull=True).count()
    
    # Room usage statistics
    room_usage = defaultdict(int)
    exams_per_room = defaultdict(set)
    
    for student_exam in StudentExam.objects.select_related('exam', 'room'):
        if student_exam.room:
            room_usage[student_exam.room.id] += 1
            exams_per_room[student_exam.room.id].add(student_exam.exam.id)
    
    # One-day gap compliance
    gap_violations = 0
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related('student', 'exam'):
        student_exams[student_exam.student.id].append(student_exam.exam.date)
    
    for student_id, dates in student_exams.items():
        dates.sort()
        for i in range(len(dates) - 1):
            if (dates[i + 1] - dates[i]).days < 2:
                gap_violations += 1
                break
    
    return {
        'total_exams': total_exams,
        'total_students': total_students,
        'unaccommodated_students': unaccommodated,
        'accommodation_rate': (total_students - unaccommodated) / total_students * 100 if total_students > 0 else 0,
        'rooms_used': len(room_usage),
        'average_students_per_room': sum(room_usage.values()) / len(room_usage) if room_usage else 0,
        'rooms_with_multiple_exams': len([r for r in exams_per_room.values() if len(r) > 1]),
        'one_day_gap_violations': gap_violations,
        'gap_compliance_rate': (len(student_exams) - gap_violations) / len(student_exams) * 100 if student_exams else 0
    }