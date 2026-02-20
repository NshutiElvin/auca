from datetime import timedelta
from django.db.models import Prefetch
from collections import defaultdict 
from datetime import datetime, time, timedelta, date
from itertools import combinations
import logging
import random
import copy   

# Django
from django.db import transaction
from django.db.models import Count, Sum

# Local Models
from courses.models import Course, CourseGroup
from enrollments.models import Enrollment
from exams.models import Exam, StudentExam
from rooms.models import Room
from schedules.models import MasterTimetable
from django.db.models import Min, Max
from datetime import timedelta, time
from bisect import bisect_left, bisect_right
from collections import defaultdict

logger = logging.getLogger(__name__)
SLOTS = [
    ("Morning",   time(8,  0), time(11, 0)),
    ("Afternoon", time(13, 0), time(16, 0)),
    ("Evening",   time(17, 0), time(20, 0)),   
]

FRIDAY_SLOTS = [SLOTS[0], SLOTS[1]]  
NO_EXAM_DAYS = ["Saturday"]          

SLOT_MAP = {label: (start, end) for label, start, end in SLOTS}



GROUP_PREFERENCES = {
    "A": "mostly morning",
    "B": "mostly morning",
    "C": "mixed",
    "D": "mixed",
    "E": "evening",
    "F": "evening",
}


def get_slots_for_day(check_date):
    """Return the list of (label, start, end) tuples allowed on check_date."""
    weekday = check_date.strftime("%A")
    if weekday in NO_EXAM_DAYS:
        return []
    if weekday == "Friday":
        return FRIDAY_SLOTS
    return SLOTS


def get_allowed_slot_names(check_date):
    """Return just the slot name strings allowed on check_date."""
    return [label for label, _, _ in get_slots_for_day(check_date)]




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
   
    conflict_matrix = defaultdict(int)

    # Get all enrollments grouped by student
    student_courses = defaultdict(list)
    for enrollment in Enrollment.objects.all():
        student_courses[enrollment.student_id].append(enrollment.course_id)

    # Build conflict matrix
    for student_id, courses in student_courses.items():
        for i, course1 in enumerate(courses):
            for course2 in courses[i + 1 :]:
                course_pair = tuple(sorted([course1, course2]))
                conflict_matrix[course_pair] += 1

    return conflict_matrix


def find_compatible_courses(course_conflict_matrix):

    all_courses = set()
    for course1, course2 in course_conflict_matrix.keys():
        all_courses.add(course1)
        all_courses.add(course2)
    enrolled_courses = Course.objects.annotate(
        enrollment_count=Count("enrollments")
    ).filter(enrollment_count__gt=0)

    for course in enrolled_courses.values_list("id", flat=True):
        all_courses.add(course)

    compatibility_graph = {course: set() for course in all_courses}
    for course1 in all_courses:
        for course2 in all_courses:
            if course1 != course2:
                pair = tuple(sorted([course1, course2]))
                if (
                    pair not in course_conflict_matrix
                    or course_conflict_matrix[pair] == 0
                ):
                    compatibility_graph[course1].add(course2)

    remaining_courses = set(all_courses)
    course_groups = []

    while remaining_courses:
        course_group = []

        if remaining_courses:
            course1 = min(
                [c for c in remaining_courses],
                key=lambda c: (
                    len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    )
                    if len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    )
                    > 0
                    else float("inf")
                ),
            )

            course_group.append(course1)
            remaining_courses.remove(course1)

            compatible_with_group = (
                set(compatibility_graph[course1]) & remaining_courses
            )

            while compatible_with_group:
             
                next_course = min(
                    compatible_with_group,
                    key=lambda c: len(
                        [rc for rc in compatibility_graph[c] if rc in remaining_courses]
                    ),
                )

                course_group.append(next_course)
                remaining_courses.remove(next_course)

                # Update the set of courses compatible with the entire group
                compatible_with_group &= set(compatibility_graph[next_course])
                compatible_with_group &= remaining_courses

        if course_group:
            course_groups.append(course_group)

    return course_groups


def get_exam_slots(start_date, end_date, max_slots=None):

    date_slots = []
    current_date = start_date

    while current_date <= end_date:
        weekday = current_date.strftime("%A")
        if weekday not in NO_EXAM_DAYS:
            slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS
            for label, start, end in slots:
                date_slots.append((current_date, label, start, end))
                if max_slots and len(date_slots) >= max_slots:
                    break
        current_date += timedelta(days=1)

    return date_slots


def get_total_room_capacity():
    """Get the total capacity of all available rooms"""
    return (
        Room.objects.filter().aggregate(total_capacity=Sum("capacity"))[
            "total_capacity"
        ]
        or 0
    )


def get_course_group(course):
    
    if hasattr(course, "group"):
        return course.group

    # Option 2: If group is in course name
    course_name = course.name or course.title
    if course_name:
        # Extract last character as group (adjust as needed)
        group_char = course_name.strip()[-1].upper()
        if group_char in GROUP_PREFERENCES:
            return group_char

    # Option 3: If course code contains group info
    if hasattr(course, "code") and course.code:
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
        enrollment_count=Count("enrollments")
    ).filter(enrollment_count__gt=0)

    # Group courses by their preference
    courses_by_preference = defaultdict(list)
    for course in enrolled_courses:
        group = get_course_group(course)
        preference = GROUP_PREFERENCES.get(group, "mixed")
        courses_by_preference[preference].append(course)

    return courses_by_preference


def get_student_exam(student_id, date, start_time):

    return StudentExam.objects.filter(
        student_id=student_id,
        exam__date=date,
        exam__start_time=start_time,
    ).first()


def check_rooms_availability_for_slots(n_students):
    """
    Check if there are enough rooms available for the given date and time slot
    """
    total_capacity = get_total_room_capacity()

    if total_capacity < n_students:
        return False

    return True


def get_occupied_seats_by_time_slot(date, start_time):

    occupied_count = StudentExam.objects.filter(
        exam__date=date,
        exam__start_time=start_time,
    ).count()

    return occupied_count


def which_suitable_slot_to_schedule_course_group(date, new_group, suggested_slot):
    all_suggestions = []
    all_conflicts = defaultdict(list)
    possible_slots = []

    day_of_week = date.weekday()

    # Early exits for optimization
    if day_of_week == 5:  # Saturday
        all_conflicts["Saturday"].append("No exams can be scheduled on Saturday")
        return new_group, None, all_suggestions, all_conflicts

    if day_of_week == 4 and suggested_slot == "Evening":  # Friday evening
        suggested_slot = "Morning"

    # Get date range once
    date_range = Exam.objects.aggregate(
        min_date=Min("date"), 
        max_date=Max("date")
    )
    min_exam_date = date_range["min_date"]
    max_exam_date = date_range["max_date"]

    # Calculate all dates to check upfront
    dates_to_check = []
    
    # Current date
    dates_to_check.append(date)
    
    # Past dates (up to min_exam_date)
    current_date = date - timedelta(days=1)
    while current_date >= min_exam_date:
        if current_date.weekday() != 5:  # Skip Saturday
            dates_to_check.append(current_date)
        current_date -= timedelta(days=1)
    
    # Future dates (up to 14 days or max_exam_date)
    for days_after in range(1, 15):
        future_date = date + timedelta(days=days_after)
        if future_date > max_exam_date or future_date.weekday() == 5:
            continue
        dates_to_check.append(future_date)

    # Bulk fetch all enrolled students for new groups
    enrolled_students_new_group = set(
        Enrollment.objects.filter(group_id__in=new_group)
        .values_list("student_id", flat=True)
    )

    # Bulk fetch all exams and related data for the date range
    all_exams = (
        Exam.objects
        .filter(date__in=dates_to_check)
        .select_related('group', 'group__course')
        .prefetch_related(
            Prefetch(
                'studentexam_set',
                queryset=StudentExam.objects.select_related('student')
            )
        )
    )

    # Pre-process exam data into efficient lookup structures
    exams_by_date_slot = defaultdict(list)
    students_by_date_slot = defaultdict(set)
    
    for exam in all_exams:
        key = (exam.date, exam.slot_name)
        exams_by_date_slot[key].append(exam)
        
        # Get all students for this exam
        exam_students = {se.student_id for se in exam.studentexam_set.all()}
        students_by_date_slot[key].update(exam_students)

    def get_available_slots_for_date(check_date):
        """Get available slots for a given date based on day of week"""
        available_slots = ["Morning", "Afternoon", "Evening"]
        if check_date.weekday() == 4:  # Friday
            available_slots.remove("Evening")
        return available_slots

    def check_slot_conflicts_optimized(check_date, slot):
        """Optimized conflict checking using pre-fetched data"""
        key = (check_date, slot)
        slot_students = students_by_date_slot.get(key, set())
        
        conflicts = []
        conflicting_students = enrolled_students_new_group.intersection(slot_students)
        
        if conflicting_students:
            # Only get exam details for conflicting students
            slot_exams = exams_by_date_slot.get(key, [])
            for student_id in conflicting_students:
                # Find the exam this student is enrolled in
                for exam in slot_exams:
                    if exam.group:
                        exam_student_ids = {se.student_id for se in exam.studentexam_set.all()}
                        if student_id in exam_student_ids:
                            conflicts.append({
                                "student": student_id,
                                "group": exam.group.group_name,
                                "course": exam.group.course.title,
                                "date": check_date,
                                "slot": slot,
                            })
                            break

        return conflicts, len(slot_students)

    def evaluate_slot_optimized(check_date, slot, is_suggested=False):
        """Optimized slot evaluation"""
        conflicts, student_count = check_slot_conflicts_optimized(check_date, slot)
        total_students = len(enrolled_students_new_group) + student_count

        suggestion_type = "Suggested slot" if is_suggested else "Slot"
        
        if conflicts:
            all_conflicts[check_date].extend(conflicts)
            all_suggestions.append({
                "suggested": False,
                "date": check_date,
                "slot": slot,
                "reason": f"{suggestion_type} {check_date} {slot} is not available (conflicts)",
            })
            return False
            
        elif not check_rooms_availability_for_slots(total_students):
            room_msg = f"{check_date} {slot} slot lacks room capacity"
            all_conflicts[check_date].append(room_msg)
            all_suggestions.append({
                "suggested": False,
                "date": check_date,
                "slot": slot,
                "reason": f"{suggestion_type} {check_date} {slot} is not available (insufficient rooms)",
            })
            return False
            
        else:
            all_suggestions.append({
                "suggested": True,
                "date": check_date,
                "slot": slot,
                "reason": f"Slot {check_date} {slot} is available",
            })
            possible_slots.append({"date": check_date, "slot": slot})
            return True

    # Process dates in priority order for early termination
    # Priority: 1) Current date with suggested slot, 2) Current date other slots, 3) Other dates
    
    # Check suggested slot on current date first
    if evaluate_slot_optimized(date, suggested_slot, is_suggested=True):
        # If suggested slot is available, we can potentially return early
        # depending on requirements
        pass

    # Check other slots on the same day
    available_slots = get_available_slots_for_date(date)
    for slot in available_slots:
        if slot != suggested_slot:
            evaluate_slot_optimized(date, slot)

    # Check other dates only if needed (based on business requirements)
    for check_date in dates_to_check[1:]:  # Skip current date (already checked)
        available_slots = get_available_slots_for_date(check_date)
        for slot in available_slots:
            evaluate_slot_optimized(check_date, slot)

    # Optimized best suggestion finding
    best_suggestion = None
    if possible_slots:
        # Group by date for faster lookup
        slots_by_date = defaultdict(list)
        for slot_info in possible_slots:
            slots_by_date[slot_info["date"]].append(slot_info)
        
        # Prioritize: same date -> suggested slot -> earliest date
        if date in slots_by_date:
            same_date_slots = slots_by_date[date]
            # Look for suggested slot first
            for slot_info in same_date_slots:
                if slot_info["slot"] == suggested_slot:
                    best_suggestion = slot_info
                    break
            if not best_suggestion:
                best_suggestion = same_date_slots[0]
        else:
            # Find earliest date
            earliest_date = min(slots_by_date.keys())
            best_suggestion = slots_by_date[earliest_date][0]

    return new_group, best_suggestion, all_suggestions, all_conflicts

 


def get_slot_name(start_time, end_time):
    """
    Get the slot name based on start and end times
    """
    if start_time == time(8, 0) and end_time == time(11, 0):
        return "Morning"
    elif start_time == time(13, 0) and end_time == time(16, 0):
        return "Afternoon"
    elif start_time == time(18, 0) and end_time == time(20, 0):
        return "Evening"
    else:
        return None
from collections import defaultdict
from django.db import models




# Alternative approach for very large datasets
def verify_groups_compatibility(groups):
    """
    Alternative implementation optimized for very large datasets.
    Uses bulk operations and minimal memory footprint.
    """
    
    # Use raw SQL for maximum performance if needed
    from django.db import connection
    
    with connection.cursor() as cursor:
        placeholders = ','.join(['%s'] * len(groups))
        cursor.execute(f"""
            SELECT course_id, group_id, student_id 
            FROM enrollments_enrollment 
            WHERE group_id IN ({placeholders})
            ORDER BY student_id, course_id, group_id
        """, groups)
        
        enrollments = cursor.fetchall()
    
    # Process results with minimal memory usage
    course_group_students = defaultdict(lambda: defaultdict(set))
    for course_id, group_id, student_id in enrollments:
        course_group_students[course_id][group_id].add(student_id)
    
    # Rest of the logic remains the same as the optimized version
    student_to_groups = defaultdict(set)
    for course_id, groups_dict in course_group_students.items():
        for group_id, students in groups_dict.items():
            for student_id in students:
                student_to_groups[student_id].add((course_id, group_id))
    
    group_conflicts = []
    processed_pairs = set()
    
    for student_id, student_groups in student_to_groups.items():
        if len(student_groups) > 1:
            student_groups_list = list(student_groups)
            for i in range(len(student_groups_list)):
                for j in range(i + 1, len(student_groups_list)):
                    course1, group1 = student_groups_list[i]
                    course2, group2 = student_groups_list[j]
                    


                    pair = tuple(sorted([(course1, group1), (course2, group2)]))
                    
                    if pair not in processed_pairs:
                        processed_pairs.add(pair)
                        students1 = course_group_students[course1][group1]
                        students2 = course_group_students[course2][group2]
                        shared_students = students1 & students2
                        
                        if shared_students:
                            group_conflicts.append((group1, group2, shared_students))
    
    return group_conflicts


def find_compatible_courses_within_group(courses, location_id=None):
    if not courses:
        return [], defaultdict(list)

    # Resolve seat capacity
    if location_id:
        total_seats = Room.objects.filter(
            location_id=location_id
        ).aggregate(total=Sum("capacity"))["total"] or 0
    else:
        first_course = Course.objects.filter(id=courses[0]).first()
        location_id = (
            first_course.department.location_id
            if first_course and first_course.department else None
        )
        total_seats = Room.objects.filter(
            location_id=location_id
        ).aggregate(total=Sum("capacity"))["total"] or 0

    max_students_per_slot = total_seats

    # Build enrollment maps
    course_students      = defaultdict(set)
    course_group_students = defaultdict(lambda: defaultdict(set))
    course_group_sizes   = defaultdict(lambda: defaultdict(int))

    enrollments = Enrollment.objects.filter(
        course_id__in=courses, status='enrolled'
    )
    missing = enrollments.filter(group__isnull=True).count()
    if missing:
        logger.warning(
            f"{missing} enrollments have no group and will be skipped."
        )

    for enr in enrollments.filter(group__isnull=False).iterator():
        course_students[enr.course_id].add(enr.student_id)
        course_group_students[enr.course_id][enr.group_id].add(enr.student_id)
        course_group_sizes[enr.course_id][enr.group_id] += 1

    # Build conflict graph between courses
    course_conflicts = defaultdict(list)
    for c1, c2 in combinations(course_students.keys(), 2):
        if course_students[c1] & course_students[c2]:
            course_conflicts[c1].append(c2)
            course_conflicts[c2].append(c1)

    # --- Greedy graph colouring (one colour = one timeslot) ---
    color_courses        = defaultdict(list)
    color_student_counts = defaultdict(int)
    color_course_groups  = defaultdict(lambda: defaultdict(list))
    colored              = {}

    # Sort: largest course first, most conflicted first
    course_list = sorted(
        course_students.keys(),
        key=lambda x: (-len(course_students[x]), -len(course_conflicts[x]))
    )

    for course in course_list:
        course_size   = len(course_students[course])
        course_groups = list(course_group_students[course].keys())

        # FIX: compute compatible count once, use 0 for isolated courses
        # (so they get a slot immediately rather than being deferred)
        available_colors = []
        for color in range(len(course_students)):
            conflict_free = all(
                colored.get(conflict) != color
                for conflict in course_conflicts[course]
                if conflict in colored
            )
            has_capacity = (
                color_student_counts[color] + course_size
            ) <= max_students_per_slot

            if conflict_free and has_capacity:
                available_colors.append(color)

        if available_colors:
            chosen = min(available_colors, key=lambda c: color_student_counts[c])
            colored[course] = chosen
            color_courses[chosen].append(course)
            color_student_counts[chosen] += course_size
            for gid in course_groups:
                color_course_groups[chosen][course].append(gid)
        else:
            # Course doesn't fit in any existing slot — split by group
            sorted_groups = sorted(
                course_groups, key=lambda g: -course_group_sizes[course][g]
            )
            for gid in sorted_groups:
                gsize = course_group_sizes[course][gid]
                best_color, best_remaining = None, float("inf")

                for color in range(len(color_student_counts) + 1):
                    if any(
                        colored.get(conflict) == color
                        for conflict in course_conflicts[course]
                        if conflict in colored
                    ):
                        continue
                    current = color_student_counts.get(color, 0)
                    remaining = max_students_per_slot - current
                    if gsize <= remaining and remaining < best_remaining:
                        best_color, best_remaining = color, remaining

                if best_color is not None:
                    color_course_groups[best_color][course].append(gid)
                    color_student_counts[best_color] = (
                        color_student_counts.get(best_color, 0) + gsize
                    )

    # Convert colour map → output format
    compatible_groups = []
    for color in sorted(color_course_groups.keys()):
        courses_in_slot, total_students = [], 0
        for course_id, gids in color_course_groups[color].items():
            slot_size = sum(
                course_group_sizes[course_id][g] for g in gids
            )
            total_students += slot_size
            courses_in_slot.append({
                "course_id": course_id,
                "groups":    gids,
                "student_count": slot_size,
                "all_groups_scheduled_together": (
                    len(gids) == len(course_group_students[course_id])
                ),
                "split_course": (
                    len(gids) < len(course_group_students[course_id])
                ),
            })
        if courses_in_slot:
            compatible_groups.append({
                "timeslot":       color + 1,
                "courses":        courses_in_slot,
                "student_count":  total_students,
                "within_capacity": total_students <= max_students_per_slot,
            })

    return compatible_groups, course_conflicts


def optimize_timeslot_adjacency(color_course_groups, color_student_counts, max_capacity, course_group_sizes):
    """Optimize timeslot arrangement to keep split courses adjacent"""
    # Find courses that are split across multiple timeslots
    split_courses = defaultdict(set)
    for color, courses in color_course_groups.items():
        for course_id in courses:
            split_courses[course_id].add(color)
    
    # Only consider courses split across multiple timeslots
    split_courses = {course: colors for course, colors in split_courses.items() if len(colors) > 1}
    
    if not split_courses:
        return
    
    # Try to rearrange timeslots to minimize distance between split courses
    color_list = sorted(color_course_groups.keys())
    
    for course_id, original_colors in split_courses.items():
        # Get current color positions
        current_min = min(original_colors)
        current_max = max(original_colors)
        current_spread = current_max - current_min
        
        # Try to find better arrangement
        best_arrangement = None
        best_spread = current_spread
        
        # Try different starting positions
        for start_color in range(len(color_list) - current_spread):
            end_color = start_color + current_spread
            candidate_colors = set(range(start_color, end_color + 1))
            
            # Check if these colors can accommodate the course groups
            feasible = True
            for color in candidate_colors:
                if color not in color_course_groups:
                    continue
                # Check for conflicts (simplified - in real implementation, check actual conflicts)
                # Check capacity
                course_groups_in_color = color_course_groups[color].get(course_id, [])
                if course_groups_in_color:
                    group_size = sum(course_group_sizes[course_id][group_id] for group_id in course_groups_in_color)
                    if color_student_counts[color] + group_size > max_capacity:
                        feasible = False
                        break
            
            if feasible and len(candidate_colors) >= len(original_colors):
                if len(candidate_colors) < best_spread:
                    best_spread = len(candidate_colors)
                    best_arrangement = candidate_colors
        
        # Apply best arrangement if found
        if best_arrangement and best_spread < current_spread:
            # Implementation would involve moving groups between timeslots
            # This is simplified - actual implementation would need to handle
            # student conflicts and capacity constraints more carefully
            pass


def find_compatible_courses_with_group_optimization(courses):
    """
    Alternative approach: First try to combine groups within courses that don't conflict,
    then find compatibility between courses.
    """
    if not courses:
        return {"compatible_groups": [], "group_conflicts": defaultdict(list)}
    
    # Data structure: {course_id: {group_id: set(student_ids)}}
    course_group_students = defaultdict(lambda: defaultdict(set))
    
    # Populate enrollment data
    for enrollment in Enrollment.objects.filter(course_id__in=courses).iterator():
        course_group_students[enrollment.course_id][enrollment.group_id].add(
            enrollment.student_id
        )
    
    # For each course, find which groups can be combined (no student overlap)
    course_combined_groups = {}
    
    for course_id, groups in course_group_students.items():
        group_list = list(groups.keys())
        combined_groups = []
        used_groups = set()
        
        for group_id in group_list:
            if group_id in used_groups:
                continue
                
            # Start a new combined group
            current_combination = [group_id]
            current_students = groups[group_id].copy()
            used_groups.add(group_id)
            
            # Try to add more groups that don't conflict
            for other_group in group_list:
                if other_group in used_groups:
                    continue
                    
                other_students = groups[other_group]
                if not (current_students & other_students):  # No overlap
                    current_combination.append(other_group)
                    current_students.update(other_students)
                    used_groups.add(other_group)
            
            combined_groups.append({
                'groups': current_combination,
                'students': current_students
            })
        
        course_combined_groups[course_id] = combined_groups
    
    # Now find compatibility between course combinations
    all_course_combinations = []
    for course_id, combinations_list in course_combined_groups.items():
        for i, combo in enumerate(combinations_list):
            all_course_combinations.append((course_id, i, combo))
    
    # Build conflict graph between course combinations
    combination_conflicts = defaultdict(list)
    for (course1, combo1_idx, combo1), (course2, combo2_idx, combo2) in combinations(all_course_combinations, 2):
        if combo1['students'] & combo2['students']:  # Student overlap
            key1 = (course1, combo1_idx)
            key2 = (course2, combo2_idx)
            combination_conflicts[key1].append(key2)
            combination_conflicts[key2].append(key1)
    
    # Greedy coloring
    color_combinations = defaultdict(list)
    colored = {}
    combination_list = sorted(all_course_combinations, 
                            key=lambda x: -len(combination_conflicts[(x[0], x[1])]))
    
    for course_id, combo_idx, combo in combination_list:
        key = (course_id, combo_idx)
        
        # Find used colors
        used_colors = {
            colored[conflict]
            for conflict in combination_conflicts[key]
            if conflict in colored
        }
        
        # Assign first available color
        for color in range(len(all_course_combinations)):
            if color not in used_colors:
                colored[key] = color
                color_combinations[color].append((course_id, combo_idx, combo))
                break
    
    # Convert to output format
    compatible_groups = []
    for color, combinations_in_slot in color_combinations.items():
        course_details = []
        total_students = 0
        
        for course_id, combo_idx, combo in combinations_in_slot:
            course_details.append({
                "course_id": course_id,
                "groups": combo['groups']
            })
            total_students += len(combo['students'])
        
        compatible_groups.append({
            "timeslot": color + 1,
            "courses": course_details,
            "student_count": total_students,
        })
    
    compatible_groups.sort(key=lambda x: -x["student_count"])
    
    return compatible_groups, combination_conflicts
 

def has_sufficient_gap(student_exam_dates, proposed_date, min_gap_days=1):
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

    student_ids = Enrollment.objects.filter(course=course, group=group).values_list(
        "student_id", flat=True
    )

    for student_id in student_ids:
        current_exam_dates = student_exam_dates.get(student_id, [])

        # Check for same-slot conflict
        same_slot_exam = StudentExam.objects.filter(
            student_id=student_id,
            exam__date=proposed_date,
            exam__start_time=course.start_time if hasattr(course, "start_time") else None,
            exam__end_time=course.end_time if hasattr(course, "end_time") else None,
        ).exists()
        if same_slot_exam:
            conflicts.append(
            f"Student {student_id} already has an exam in the same slot on {proposed_date}"
            )
            continue

       

    return len(conflicts) == 0, conflicts


def remove_scheduled_group(scheduled_groups, course_id, group_id):
    """Remove a specific group from scheduled groups"""
    for course_group in scheduled_groups:
        for course_dict in course_group["courses"]:
            if (
                course_dict["course_id"] == course_id
                and group_id in course_dict["groups"]
            ):
                course_dict["groups"].remove(group_id)
                return True
    return False


def clean_empty_courses_from_group(course_group):
    """Remove courses with no groups from a course_group"""
    course_group["courses"] = [
        course for course in course_group["courses"] if course["groups"]
    ]
    return len(course_group["courses"]) > 0


def get_exam_time_for_group(available_slots, available_seats=None,
                             slots_usage=None, needed_seats=None):
    """
    Return the first slot name from available_slots that has enough
    remaining room capacity.

    Parameters
    ----------
    available_slots : list[str]
        Ordered list of slot names allowed on the day, e.g.
        ["Morning", "Afternoon"] on a Friday.
    available_seats : int or None
        Total seat capacity of all rooms combined.
    slots_usage : dict[str, int] or None
        How many seats are already used per slot name.
    needed_seats : int or None
        How many seats the new group of students needs.
    """
    if not available_slots:
        return None

    # If we have no capacity data, just return the first available slot
    if available_seats is None or needed_seats is None or slots_usage is None:
        return available_slots[0]

    for slot_name in available_slots:          # FIX: iterate available_slots, not slots_usage
        already_used = slots_usage.get(slot_name, 0)
        if already_used + needed_seats <= available_seats:
            return slot_name

    return None  # No slot has enough capacity

 


def fetch_courses(course_ids):
    if course_ids:
        return {c.id: c for c in Course.objects.filter(id__in=course_ids)}
    # else fetch all courses with enrollments
    courses_qs = Course.objects.annotate(enrollment_count=Count("enrollments")).filter(enrollment_count__gt=0)
    return {c.id: c for c in courses_qs}


def fetch_course_groups(group_ids):
    return {g.id: g for g in CourseGroup.objects.filter(id__in=group_ids)}


def get_slots_by_date(slots_input):
    slots_by_date = {}
    for date_str, value in slots_input.items():
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slots_by_date[date] = value
    return slots_by_date


def prefetch_enrollments(course_groups):
    """
    Prefetch enrollments for all groups in course_groups.
    Returns a dictionary mapping group ID to a set of student IDs.
    """
    group_ids = []
    for group in course_groups:
        for course in group["courses"]:
            group_ids.extend(course["groups"])
    
    enrollments = Enrollment.objects.filter(group_id__in=group_ids, status='enrolled').values('group_id', 'student_id')
    enrollments_by_group = defaultdict(set)
    for enrollment in enrollments:
        enrollments_by_group[enrollment['group_id']].add(enrollment['student_id'])
    
    return dict(enrollments_by_group)


def verify_day_off_constraints(min_gap_days=1):
    """
    Verify that the current schedule maintains day-off constraints
    """
    violations = []

    # Get all student exam dates
    student_exam_dates = defaultdict(list)
    for student_exam in StudentExam.objects.select_related("student", "exam"):
        student_exam_dates[student_exam.student.id].append(student_exam.exam.date)

    # Check each student's schedule
    for student_id, exam_dates in student_exam_dates.items():
        if len(exam_dates) < 2:
            continue

        sorted_dates = sorted(exam_dates)
        for i in range(len(sorted_dates) - 1):
            gap = (sorted_dates[i + 1] - sorted_dates[i]).days
            if gap < min_gap_days:
                violations.append(
                    f"Student {student_id}: {gap} day gap between {sorted_dates[i]} and {sorted_dates[i + 1]}"
                )

    return violations


def are_semesters_compatible(exam1, exam2):
    # Returns True if semesters have a gap of at least 2
    return (
        abs(
            int(exam1.course.semester.name.split(" ")[1])
            - int(exam2.course.semester.name.split(" ")[1])
        )
        > 1
    )


def allocate_single_exam_rooms(exam):
    """
    Allocate students to rooms for a single exam
    Returns a list of students who couldn't be accommodated
    """
    rooms = list(Room.objects.order_by("-capacity"))

    if not rooms:
        raise Exception("No rooms available for allocation.")

    student_exam_qs = StudentExam.objects.filter(exam=exam).select_related("student")
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

        chunk = unassigned[: room.capacity]
        for se in chunk:
            se.room = room
            se.save(update_fields=["room"])

        unassigned = unassigned[room.capacity :]

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
        weekday = new_date.strftime("%A")
        if weekday in NO_EXAM_DAYS:
            raise ValueError(f"Cannot schedule an exam on {weekday}.")

        # 2. VALIDATE AND SET TIME SLOT
        new_start_time = exam.start_time  # Default to current time
        new_end_time = exam.end_time

        if slot:
            # Friday slot validation
            if weekday == "Friday":
                available_slots = FRIDAY_SLOTS
            else:
                available_slots = SLOTS

            slot_match = next(
                (s for s in available_slots if s[0].lower() == slot.lower()), None
            )
            if not slot_match:
                available_slot_names = [s[0] for s in available_slots]
                raise ValueError(
                    f"Invalid slot '{slot}' for {weekday}. "
                    f"Available slots: {', '.join(available_slot_names)}"
                )

            _, new_start_time, new_end_time = slot_match
        else:
            # If no slot specified, validate current time slot is valid for the new day
            if weekday == "Friday":
                # Check if current time slot is valid for Friday
                current_slot = (exam.start_time, exam.end_time)
                friday_times = [(start, end) for _, start, end in FRIDAY_SLOTS]

                if current_slot not in friday_times:
                    available_slots = [
                        f"{label} ({start}-{end})" for label, start, end in FRIDAY_SLOTS
                    ]
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
                student=enrollment.student, exam__date=new_date
            ).exclude(exam_id=exam_id)

            if existing_exams.exists():
                conflicted_students.append(
                    {
                        "student": enrollment.student.reg_no,
                        "conflicting_exams": [
                            se.exam.course.title for se in existing_exams
                        ],
                    }
                )

        if conflicted_students:
            conflict_details = []
            for conflict in conflicted_students[:3]:
                courses = ", ".join(conflict["conflicting_exams"])
                conflict_details.append(
                    f"{conflict['student']} (conflicts with: {courses})"
                )

            error_msg = f"Student conflicts found: {'; '.join(conflict_details)}"
            if len(conflicted_students) > 3:
                error_msg += f" ... and {len(conflicted_students) - 3} more students"

            raise ValueError(error_msg)

        # 4. CHECK ROOM CAPACITY CONFLICTS
        # Get number of students for this exam
        exam_student_count = Enrollment.objects.filter(course=exam.course).count()

        # Check existing exams in the same time slot
        existing_slot_exams = Exam.objects.filter(
            date=new_date, start_time=new_start_time, end_time=new_end_time
        ).exclude(id=exam_id)

        # Calculate total students that would need accommodation in this slot
        total_students_needed = exam_student_count
        other_exams_students = 0

        for other_exam in existing_slot_exams:
            other_exam_students = Enrollment.objects.filter(
                course=other_exam.course
            ).count()
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
                Enrollment.objects.filter(course=exam.course).values_list(
                    "student_id", flat=True
                )
            )

            for other_exam in existing_slot_exams:
                other_students = set(
                    Enrollment.objects.filter(course=other_exam.course).values_list(
                        "student_id", flat=True
                    )
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
                student_count = Enrollment.objects.filter(
                    course=slot_exam.course
                ).count()
                room_requirements.append(student_count)

            # Check if we can fit all exams in available rooms
            rooms = list(Room.objects.order_by("-capacity"))
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
        slot_exams = list(
            Exam.objects.filter(
                date=new_date, start_time=new_start_time, end_time=new_end_time
            )
        )

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

        weekday = current.strftime("%A")
        if weekday in NO_EXAM_DAYS:
            current += timedelta(days=1)
            continue

        # Get available slots for this day
        available_slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS

        for slot_name, start_time, end_time in available_slots:
            try:
                # Test if this slot would work (without actually rescheduling)
                test_conflicts = check_reschedule_feasibility(
                    exam_id, current, slot_name
                )
                if not test_conflicts:
                    suggestions.append(
                        {
                            "date": current,
                            "slot": slot_name,
                            "start_time": start_time,
                            "end_time": end_time,
                            "weekday": weekday,
                        }
                    )
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
        weekday = new_date.strftime("%A")

        # Check day validity
        if weekday in NO_EXAM_DAYS:
            conflicts.append(f"Cannot schedule on {weekday}")
            return conflicts

        # Check slot validity
        available_slots = FRIDAY_SLOTS if weekday == "Friday" else SLOTS
        slot_match = next(
            (s for s in available_slots if s[0].lower() == slot_name.lower()), None
        )
        if not slot_match:
            conflicts.append(f"Invalid slot '{slot_name}' for {weekday}")
            return conflicts

        _, new_start_time, new_end_time = slot_match

        # Check student conflicts
        enrolled_students = Enrollment.objects.filter(course=exam.course)
        student_conflicts = 0

        for enrollment in enrolled_students:
            existing_exams = StudentExam.objects.filter(
                student=enrollment.student, exam__date=new_date
            ).exclude(exam_id=exam_id)

            if existing_exams.exists():
                student_conflicts += 1

        if student_conflicts > 0:
            conflicts.append(f"{student_conflicts} student conflicts")

        # Check room capacity
        exam_students = Enrollment.objects.filter(course=exam.course).count()
        existing_slot_exams = Exam.objects.filter(
            date=new_date, start_time=new_start_time, end_time=new_end_time
        ).exclude(id=exam_id)

        total_students = exam_students
        for other_exam in existing_slot_exams:
            total_students += Enrollment.objects.filter(
                course=other_exam.course
            ).count()

        total_capacity = get_total_room_capacity()
        if total_students > total_capacity:
            conflicts.append(
                f"Insufficient capacity ({total_students} needed, {total_capacity} available)"
            )

    except Exception as e:
        conflicts.append(f"Error checking feasibility: {str(e)}")

    return conflicts


def get_unaccommodated_students():
    """
    Get a list of students who couldn't be accommodated in the exam schedule
    """
    # Students without a room assignment
    unaccommodated = StudentExam.objects.filter(room__isnull=True).select_related(
        "student", "exam__course"
    )

    result = []
    for student_exam in unaccommodated:
        result.append(
            {
                "student": student_exam.student,
                "course": student_exam.exam.course,
                "exam_date": student_exam.exam.date,
                "exam_slot": (student_exam.exam.start_time, student_exam.exam.end_time),
            }
        )

    return result


def verify_exam_schedule():
    """
    Verify that the current exam schedule has no conflicts
    Returns a list of any conflicts found
    """
    conflicts = []

    # Check for students with multiple exams in one day
    student_exams = defaultdict(list)
    for student_exam in StudentExam.objects.select_related("student", "exam"):
        student_exams[student_exam.student.id].append(student_exam)

    for student_id, exams in student_exams.items():
        exams_by_date = defaultdict(list)
        for exam in exams:
            exams_by_date[exam.exam.date].append(exam)

        for date, day_exams in exams_by_date.items():
            if len(day_exams) > 1:
                conflicts.append(
                    {
                        "type": "multiple_exams_per_day",
                        "student_id": student_id,
                        "date": date,
                        "exams": [e.exam.id for e in day_exams],
                    }
                )

    # Check for room overallocation
    exams_by_slot = defaultdict(list)
    for exam in Exam.objects.all():
        slot_key = (exam.date, exam.start_time, exam.end_time)
        exams_by_slot[slot_key].append(exam)

    for slot, slot_exams in exams_by_slot.items():
        room_student_counts = defaultdict(lambda: defaultdict(int))

        for exam in slot_exams:
            student_exams = StudentExam.objects.filter(exam=exam).select_related("room")
            for se in student_exams:
                if se.room:
                    room_student_counts[se.room.id][exam.id] += 1

        for room_id, exam_counts in room_student_counts.items():
            room = Room.objects.get(id=room_id)
            total_students = sum(exam_counts.values())

            if total_students > room.capacity:
                conflicts.append(
                    {
                        "type": "room_overallocation",
                        "room_id": room_id,
                        "capacity": room.capacity,
                        "allocated": total_students,
                        "slot": slot,
                        "exams": list(exam_counts.keys()),
                    }
                )

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
            for exam2 in slot_exams[i + 1 :]:
                # Check if these exams share any students
                students1 = set(
                    Enrollment.objects.filter(course=exam1.course).values_list(
                        "student_id", flat=True
                    )
                )
                students2 = set(
                    Enrollment.objects.filter(course=exam2.course).values_list(
                        "student_id", flat=True
                    )
                )

                common_students = students1.intersection(students2)
                if common_students:
                    conflicts.append(
                        {
                            "type": "student_exam_conflict",
                            "course1": exam1.course.id,
                            "course2": exam2.course.id,
                            "common_students": list(common_students),
                            "slot": slot,
                        }
                    )

    return conflicts




def schedule_unscheduled_group(course_id, group_id):
    try:
        enrolled_students = set(
            Enrollment.objects.filter(
                course_id=course_id, group_id=group_id
            ).values_list("student_id", flat=True)
        )
        if not enrolled_students:
            logger.info(f"No students enrolled: course={course_id}, group={group_id}")
            return False

        exam_dates = Exam.objects.aggregate(
            min_date=Min("date"), max_date=Max("date")
        )
        min_date = exam_dates["min_date"]
        max_date = exam_dates["max_date"]
        if not min_date or not max_date:
            logger.info("No exams exist in the system yet.")
            return False

        # Pre-fetch student exam history
        student_exams_qs = StudentExam.objects.filter(
            student_id__in=enrolled_students
        ).select_related("exam")

        # student_exams_map[student_id][date] = set of slot_names
        student_exams_map  = defaultdict(lambda: defaultdict(set))
        # slot_usage_map[date][slot_name] = seat count already used
        slot_usage_map     = defaultdict(lambda: defaultdict(int))

        for se in student_exams_qs:
            student_exams_map[se.student_id][se.exam.date].add(se.exam.slot_name)

        # Also pre-load slot usage across ALL students for capacity checks
        all_se = StudentExam.objects.filter(
            exam__date__range=(min_date, max_date)
        ).values("exam__date", "exam__slot_name").annotate(cnt=Count("id"))
        for row in all_se:
            slot_usage_map[row["exam__date"]][row["exam__slot_name"]] += row["cnt"]

        for day_offset in range((max_date - min_date).days + 1):
            current_date = min_date + timedelta(days=day_offset)
            allowed_slots = get_allowed_slot_names(current_date)
            if not allowed_slots:
                continue  # Saturday or holiday

            # FIX B: Only check students who are IN THIS GROUP
            # Before: any student in the system with 2 exams blocked the day
            group_has_conflict = any(
                len(student_exams_map[sid].get(current_date, set())) >= 1
                for sid in enrolled_students
            )
            if group_has_conflict:
                continue  # At least one student already has an exam this day

            # Determine room capacity for this course's location
            location = (
                Enrollment.objects.filter(
                    course_id=course_id, group_id=group_id
                ).select_related("course__department__location")
                .first()
            )
            if not location:
                continue
            loc_obj = location.course.department.location
            slot_capacity = Room.objects.filter(
                location=loc_obj
            ).aggregate(total=Sum("capacity"))["total"] or 0

            # FIX C: Call get_exam_time_for_group with correct arguments
            slot_name = get_exam_time_for_group(
                available_slots=allowed_slots,
                available_seats=slot_capacity,
                slots_usage=slot_usage_map[current_date],
                needed_seats=len(enrolled_students),
            )
            if not slot_name:
                continue  # No slot has enough room capacity

            st_time, en_time = SLOT_MAP[slot_name]  # Use central SLOT_MAP

            total_students_in_slot = slot_usage_map[current_date][slot_name]
            if total_students_in_slot + len(enrolled_students) > slot_capacity:
                continue

            # Create Exam record
            group_obj = CourseGroup.objects.get(id=group_id)
            exam = Exam.objects.create(
                date=current_date,
                start_time=st_time,
                end_time=en_time,
                group=group_obj,
                slot_name=slot_name,
            )

            # Create StudentExam records in bulk
            student_exams = StudentExam.objects.bulk_create([
                StudentExam(student_id=sid, exam=exam)
                for sid in enrolled_students
            ])

            # Allocate rooms
            success = allocate_shared_rooms_updated(
                student_exams, loc_obj, current_date, st_time, en_time
            )
            if not success:
                exam.delete()
                logger.warning(
                    f"Room allocation failed: course={course_id}, "
                    f"group={group_id}, date={current_date}"
                )
                continue

            logger.info(
                f"Scheduled course={course_id}, group={group_id} "
                f"on {current_date} [{slot_name}]"
            )
            return True

        return False   

    except Exception as exc:
        logger.error(
            f"Error scheduling course={course_id}, group={group_id}: {exc}",
            exc_info=True
        )
        return False

def allocate_shared_rooms_updated(student_exams, location=None, exam_date=None, start_time=None, end_time=None):
   
    if not student_exams:
        return True
     
    if location is None:
        location = student_exams[0].exam.group.course.department.location
    
    rooms = list(Room.objects.filter(location=location).order_by("-capacity"))
    if not rooms:
        raise Exception("No rooms available for allocation.")

    

    with transaction.atomic():
        # Get current room occupancy for this time slot
        room_occupancy = {}
        for room in rooms:
            # Count students already assigned to this room at this time
            occupied_count = StudentExam.objects.filter(
                room=room,
                exam__date=exam_date or student_exams[0].exam.date,
                exam__start_time=start_time or student_exams[0].exam.start_time,
                exam__end_time=end_time or student_exams[0].exam.end_time
            ).count()
            room_occupancy[room.id] = {
                'occupied': occupied_count,
                'available': room.capacity - occupied_count,
                'room': room
            }

        # Organize students by exam
        exams_students = defaultdict(list)
        for se in student_exams:
            exams_students[se.exam].append(se)

        # Sort exams by size (largest first for better packing)
        sorted_exams = sorted(exams_students.items(), key=lambda x: -len(x[1]))

        unassigned_students = []
        
        # Try to assign each exam to available rooms
        for exam, students in sorted_exams:
            students_to_assign = students.copy()
            
            # Try to fit this exam in available rooms
            for room_id, room_info in sorted(room_occupancy.items(), key=lambda x: -x[1]['available']):
                if not students_to_assign or room_info['available'] <= 0:
                    continue
                    
                # Assign as many students as possible to this room
                can_assign = min(len(students_to_assign), room_info['available'])
                assigned_students = students_to_assign[:can_assign]
                
                # Update database
                StudentExam.objects.filter(
                    id__in=[se.id for se in assigned_students]
                ).update(room_id=room_id)
                
                # Update tracking
                students_to_assign = students_to_assign[can_assign:]
                room_occupancy[room_id]['occupied'] += can_assign
                room_occupancy[room_id]['available'] -= can_assign
                
                print(f"Assigned {can_assign} students from exam {exam.id} to room {room_info['room'].name}")
            
            # Track any students that couldn't be assigned
            unassigned_students.extend(students_to_assign)

        # Final attempt for any remaining students (one by one)
        for se in unassigned_students:
            assigned = False
            for room_id, room_info in room_occupancy.items():
                if room_info['available'] > 0:
                    se.room_id = room_id
                    se.save()
                    room_occupancy[room_id]['occupied'] += 1
                    room_occupancy[room_id]['available'] -= 1
                    assigned = True
                    break
            
            if not assigned:
                print(f"Could not assign student {se.student_id} to any room")
                return False

        print(f"Successfully allocated all {len(student_exams)} students to rooms")
        return True


# Optional: Add a verification function
def verify_room_capacity():
    """
    Verify that no rooms are over capacity.
    Returns a list of violations.
    """
    violations = []
    
    # Group by exam details to check each time slot
    exams = Exam.objects.all()
    
    for exam in exams:
        location = exam.group.course.department.location
        rooms = Room.objects.filter(location=location)
        
        for room in rooms:
            # Count students in this room at this exact time
            student_count = StudentExam.objects.filter(
                room=room,
                exam__date=exam.date,
                exam__start_time=exam.start_time,
                exam__end_time=exam.end_time
            ).count()
            
            if student_count > room.capacity:
                violations.append({
                    'room': room.name,
                    'capacity': room.capacity,
                    'assigned': student_count,
                    'overflow': student_count - room.capacity,
                    'date': exam.date,
                    'time': f"{exam.start_time}-{exam.end_time}"
                })
    
    return violations



# def allocate_shared_rooms(location_id):
#     """
#     Allocates available rooms to students for scheduled exams.
#     Optimizes room utilization by allowing multiple exams to share a room.
#     Splits exams across multiple rooms when they exceed a single room's capacity.
#     """
#     # 1. Fetch distinct slots that need allocation to process iteratively (Memory Optimization)
#     slots_to_allocate = (
#         StudentExam.objects.filter(
#             room__isnull=True,
#             exam__group__course__department__location_id=location_id
#         )
#         .values_list("exam__date", "exam__start_time", "exam__end_time")
#         .distinct()
#     )
    
#     if not slots_to_allocate:
#         logger.info(f"No students needing room allocation for location {location_id}")
#         return []
    
#     # 2. Get all rooms at this location, largest first
#     rooms = list(Room.objects.filter(location_id=location_id).order_by("-capacity"))
#     if not rooms:
#         logger.error(f"No rooms found for location {location_id}")
#         # Return all students as unaccommodated
#         return list(StudentExam.objects.filter(
#             room__isnull=True,
#             exam__group__course__department__location_id=location_id
#         ).values_list('student', flat=True))

#     unaccommodated_students = []
    
#     # 3. Process each slot individually to save memory
#     for date, start, end in slots_to_allocate:
#         # Fetch students for this specific slot
#         student_exams = (
#             StudentExam.objects.filter(
#                 room__isnull=True,
#                 exam__group__course__department__location_id=location_id,
#                 exam__date=date,
#                 exam__start_time=start,
#                 exam__end_time=end
#             )
#             .select_related("exam", "student")
#         )
        
#         # Group by exam
#         exams_in_slot = defaultdict(list)
#         for se in student_exams:
#             exams_in_slot[se.exam].append(se)
            
#         with transaction.atomic():
#             # List of (Exam, [StudentExam])
#             exam_assignments = list(exams_in_slot.items())
#             # Sort exams by size to help with packing
#             exam_assignments.sort(key=lambda x: len(x[1]), reverse=True)
            
#             # Track capacity for each room in this slot
#             room_capacities = {r.id: r.capacity for r in rooms}
            
#             # Check existing occupancy for this slot (if any)
#             for room in rooms:
#                 occupied = StudentExam.objects.filter(
#                     room=room,
#                     exam__date=date,
#                     exam__start_time=start,
#                     exam__end_time=end
#                 ).count()
#                 room_capacities[room.id] -= occupied

#             # Distribute students
#             for exam, students in exam_assignments:
#                 remaining_students = list(students)
                
#                 # Try to fit in rooms proportionally
#                 for room in rooms:
#                     if not remaining_students: break
                    
#                     capacity = room_capacities[room.id]
#                     if capacity <= 0: continue
                    
#                     take = min(len(remaining_students), capacity)
#                     assigned_students = remaining_students[:take]
                    
#                     # Bulk update StudentExam.room
#                     StudentExam.objects.filter(
#                         id__in=[se.id for se in assigned_students]
#                     ).update(room=room)
                    
#                     room_capacities[room.id] -= take
#                     remaining_students = remaining_students[take:]
                
#                 if remaining_students:
#                     unaccommodated_students.extend([se.student for se in remaining_students])
            
#             # Update Exam.room if the exam is entirely in one room
#             for exam, students in exams_in_slot.items():
#                 room_ids = StudentExam.objects.filter(exam=exam).values_list('room_id', flat=True).distinct()
#                 if room_ids.count() == 1 and room_ids[0] is not None:
#                     exam.room_id = room_ids[0]
#                     exam.save(update_fields=['room'])
#                 else:
#                     # Exam is split across rooms
#                     exam.room = None
#                     exam.save(update_fields=['room'])

#     return unaccommodated_students


def allocate_shared_rooms(location_id):
    """
    Allocates rooms using strict equal-split (half-half) seating.

    RULE:
        Each room divides its seats EQUALLY across all exams in the slot.
        Room capacity 70, 2 exams → 35 seats each.
        Room capacity 70, 4 exams → 17 seats each (+ 2 remainder to largest exams).

        If an exam has fewer students than its share, its unused seats are
        redistributed equally to the remaining exams that still have students.

        Leftover students (those beyond one room's equal share) go to the
        next room where the same equal-split rule applies again.

    PRIORITY:
        1. Fill largest rooms first.
        2. Equal seats per exam per room wherever possible.
        3. Redistribute unused shares to exams that still have students.
        4. Overflow to next room — same rule restarts.

    Example:
        Slot has Exam 1 (40 students) and Exam 2 (55 students).
        Room capacity = 70.

        Equal share per exam = floor(70 / 2) = 35
        Exam 1 takes 35  (has 40, 5 left over → go to next room)
        Exam 2 takes 35  (has 55, 20 left over → go to next room)
        Room 1 seated = 70 ✅

        Next room gets:  Exam 1 (5 remaining), Exam 2 (20 remaining)
        Equal share = floor(room_capacity / 2) each, capped at what's left.
    """

    # ── 1. Find slots needing allocation ──────────────────────────────────────
    slots_to_allocate = list(
        StudentExam.objects.filter(
            room__isnull=True,
            exam__group__course__department__location_id=location_id,
        )
        .values_list("exam__date", "exam__start_time", "exam__end_time")
        .distinct()
    )

    if not slots_to_allocate:
        logger.info(f"No students needing room allocation for location {location_id}")
        return []

    # ── 2. Rooms sorted largest first ─────────────────────────────────────────
    rooms = list(
        Room.objects.filter(location_id=location_id).order_by("-capacity")
    )
    if not rooms:
        logger.error(f"No rooms found for location {location_id}")
        return list(
            StudentExam.objects.filter(
                room__isnull=True,
                exam__group__course__department__location_id=location_id,
            ).values_list("student", flat=True)
        )

    unaccommodated_students = []

    # ── 3. Process each time slot ─────────────────────────────────────────────
    for date, start, end in slots_to_allocate:

        student_exams_qs = (
            StudentExam.objects.filter(
                room__isnull=True,
                exam__group__course__department__location_id=location_id,
                exam__date=date,
                exam__start_time=start,
                exam__end_time=end,
            )
            .select_related("exam", "student")
        )

        exams_students = defaultdict(list)
        for se in student_exams_qs:
            exams_students[se.exam].append(se)

        if not exams_students:
            continue

        # Mutable queues — consumed as rooms are filled
        exam_queues = {exam: list(ses) for exam, ses in exams_students.items()}

        with transaction.atomic():

            # Account for students already seated (re-run safety)
            room_available = {}
            for room in rooms:
                already = StudentExam.objects.filter(
                    room=room,
                    exam__date=date,
                    exam__start_time=start,
                    exam__end_time=end,
                ).count()
                room_available[room.id] = room.capacity - already

            # ── 4. Fill rooms largest-first, equal split per exam ─────────────
            for room in rooms:
                seats_left = room_available[room.id]
                if seats_left <= 0:
                    continue

                # Only exams that still have unassigned students
                active = {e: q for e, q in exam_queues.items() if q}
                if not active:
                    break

                n_exams = len(active)

                # ── Equal share calculation ───────────────────────────────────
                # Base equal share per exam
                base_share = seats_left // n_exams
                remainder  = seats_left % n_exams   # leftover seats from floor division

                # Each exam gets base_share seats, capped by how many it has left.
                # If an exam has fewer students than base_share, the unused seats
                # are pooled and redistributed equally to exams that still need more.
                allocation = {}
                for exam, queue in active.items():
                    allocation[exam] = min(base_share, len(queue))

                # Redistribute unused seats from small exams
                # (those that had fewer students than base_share)
                unused = sum(
                    base_share - allocation[e]
                    for e in active
                    if len(active[e]) < base_share
                )

                # Also add the floor-division remainder seats
                pool = unused + remainder

                if pool > 0:
                    # Give extra seats to exams that can still absorb them
                    # (those whose queue > base_share), largest queue first
                    can_absorb = sorted(
                        [e for e in active if len(active[e]) > base_share],
                        key=lambda e: -len(active[e]),
                    )
                    for exam in can_absorb:
                        if pool <= 0:
                            break
                        extra = min(pool, len(active[exam]) - allocation[exam])
                        allocation[exam] += extra
                        pool -= extra

                # ── Assign students to this room ──────────────────────────────
                ids_to_update = []
                for exam, take in allocation.items():
                    if take <= 0:
                        continue
                    actual            = min(take, len(exam_queues[exam]))
                    assigned          = exam_queues[exam][:actual]
                    exam_queues[exam] = exam_queues[exam][actual:]
                    ids_to_update.extend(se.id for se in assigned)

                if ids_to_update:
                    StudentExam.objects.filter(id__in=ids_to_update).update(room=room)
                    logger.debug(
                        f"Room '{room.name}' ({room.capacity} seats) | "
                        f"{date} [{start}–{end}] | "
                        f"Seated {len(ids_to_update)} students | "
                        f"Split: { {str(e.id): v for e, v in allocation.items()} }"
                    )

            # ── 5. Collect overflow ───────────────────────────────────────────
            for exam, leftover in exam_queues.items():
                if leftover:
                    logger.warning(
                        f"Exam {exam.id} | {date} [{start}–{end}] | "
                        f"{len(leftover)} students could not be seated"
                    )
                    unaccommodated_students.extend(se.student for se in leftover)

            # ── 6. Update Exam.room ───────────────────────────────────────────
            for exam in exams_students:
                distinct_rooms = list(
                    StudentExam.objects.filter(exam=exam)
                    .values_list("room_id", flat=True)
                    .distinct()
                )
                exam.room_id = (
                    distinct_rooms[0]
                    if len(distinct_rooms) == 1 and distinct_rooms[0]
                    else None
                )
                exam.save(update_fields=["room"])

    return unaccommodated_students


def _student_violates_gap(sorted_exam_dates, proposed_date, min_gap_days):
    """
    Return True if proposed_date is within min_gap_days of any
    date already in sorted_exam_dates (a sorted list of date objects).
    O(log n) using binary search.
    """
    if not sorted_exam_dates or min_gap_days <= 0:
        return False
    lo = bisect_left(sorted_exam_dates,
                     proposed_date - timedelta(days=min_gap_days))
    hi = bisect_right(sorted_exam_dates,
                      proposed_date + timedelta(days=min_gap_days))
    nearby = sorted_exam_dates[lo:hi]
    return any(d != proposed_date for d in nearby)


def prefetch_enrollments(course_groups):
    """Return {group_id: set(student_ids)} for all groups in course_groups."""
    group_ids = []
    for group in course_groups:
        for course in group["courses"]:
            group_ids.extend(course["groups"])
    rows = Enrollment.objects.filter(
        group_id__in=group_ids, status='enrolled'
    ).values('group_id', 'student_id')
    result = defaultdict(set)
    for row in rows:
        result[row['group_id']].add(row['student_id'])
    return dict(result)


def get_slots_by_date(slots_input):
    result = {}
    for date_str, value in slots_input.items():
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        result[d] = value
    return result


def fetch_courses(course_ids):
    if course_ids:
        return {c.id: c for c in Course.objects.filter(id__in=course_ids)}
    qs = Course.objects.annotate(
        enrollment_count=Count("enrollments")
    ).filter(enrollment_count__gt=0)
    return {c.id: c for c in qs}


def fetch_course_groups(group_ids):
    return {g.id: g for g in CourseGroup.objects.filter(id__in=group_ids)}


def get_total_room_capacity():
    return Room.objects.aggregate(
        total=Sum("capacity")
    )["total"] or 0


def generate_exam_schedule(
    slots=None, course_ids=None,
    master_timetable: MasterTimetable = None,
    location=None, constraints=None
):
    """
    Main entry point. Builds a full exam timetable respecting:
      - Room capacity (per location)
      - Student conflict constraints (no two exams same slot)
      - Max exams per day per student
      - Minimum gap between exam days
      - SDA no-Saturday rule
      - Friday evening exclusion
    """
    try:
        if not constraints:
            constraints = {}

        time_constraints    = constraints.get("time_constraints", {})
        student_constraints = constraints.get("student_constraints", {})
        room_constraints    = constraints.get("room_constraints", {})
        group_preferences   = constraints.get("group_preferences", {})
        course_constraints  = constraints.get("course_constraints", {})

        # Time slot definitions (from constraints or hardcoded fallback)
        defined_time_slots = time_constraints.get("time_slots", [])
        if not defined_time_slots:
            defined_time_slots = [
                {"name": "Morning",   "start_time": "08:00", "end_time": "11:00", "priority": 1},
                {"name": "Afternoon", "start_time": "13:00", "end_time": "16:00", "priority": 2},
                {"name": "Evening",   "start_time": "17:00", "end_time": "20:00", "priority": 3},
            ]
        defined_time_slots.sort(key=lambda x: x.get("priority", 99))

        day_restrictions = time_constraints.get("day_restrictions", {})
        no_exam_days     = day_restrictions.get("no_exam_days", ["Saturday"])
        special_rules    = day_restrictions.get("special_rules", {})
        holidays         = day_restrictions.get("holidays", [])

        holiday_dates = set()
        for h in holidays:
            if isinstance(h, str):
                try:
                    holiday_dates.add(datetime.strptime(h, "%Y-%m-%d").date())
                except ValueError:
                    pass
            elif isinstance(h, (datetime, date)):
                holiday_dates.add(h if isinstance(h, date) else h.date())

        if not course_ids:
            course_ids = list(
                Course.objects.annotate(
                    enrollment_count=Count("enrollments")
                ).filter(enrollment_count__gt=0).values_list("id", flat=True)
            )

        # Step 1 — compatibility grouping
        compatible_groups, course_conflicts = find_compatible_courses_within_group(
            course_ids, location_id=location
        )
        if not compatible_groups:
            return [], "No compatible course groups found", [], {}

        # Step 2 — date list
        slots_by_date = get_slots_by_date(slots) if slots else {}
        dates = sorted([
            d for d in slots_by_date
            if d.strftime("%A") not in no_exam_days and d not in holiday_dates
        ])
        if not dates:
            reasons = {}
            for g in compatible_groups:
                for c in g["courses"]:
                    for gid in c["groups"]:
                        reasons[gid] = "No available dates"
            return [], [], compatible_groups, reasons

        # Step 3 — pre-fetch data
        total_seats = Room.objects.filter(
            location_id=location
        ).aggregate(total=Sum("capacity"))["total"] or 0
        buffer_pct       = room_constraints.get("capacity_buffer_percent", 0)
        effective_seats  = int(total_seats * (1 - buffer_pct / 100.0))

        enrollments_by_group = prefetch_enrollments(compatible_groups)
        all_group_ids = {
            gid
            for g in compatible_groups
            for c in g["courses"]
            for gid in c["groups"]
        }
        groups_dict  = fetch_course_groups(all_group_ids)
        courses_dict = fetch_courses(course_ids)

        # Step 4 — state tracking
        # student_daily_exams[student_id][date] = set of slot_names
        student_daily_exams = defaultdict(lambda: defaultdict(set))
        # student_sorted_dates[student_id] = sorted list of exam dates
        # FIX #8: keep sorted list per student for O(log n) gap check
        student_sorted_dates = defaultdict(list)

        existing_exams = Exam.objects.filter(date__in=dates).prefetch_related(
            "studentexam_set"
        )
        for ex in existing_exams:
            for se in ex.studentexam_set.all():
                student_daily_exams[se.student_id][ex.date].add(ex.slot_name)
                # Insert date in sorted order
                import bisect
                bisect.insort(student_sorted_dates[se.student_id], ex.date)

        slot_seats_usage = defaultdict(lambda: defaultdict(int))
        for ex in existing_exams:
            slot_seats_usage[ex.date][ex.slot_name] += ex.studentexam_set.count()

        # Step 5 — scheduling loop
        exams_created      = []
        unscheduled_groups = []
        unscheduled_reasons = {}

        max_exams_per_day  = student_constraints.get("max_exams_per_day", 1)
        max_exams_per_slot = student_constraints.get("max_exams_per_slot", 1)
        min_gap_days       = student_constraints.get("min_gap_between_exams_days", 0)

        with transaction.atomic():
            remaining = copy.deepcopy(compatible_groups)
            if course_constraints.get("prioritize_large_courses", True):
                remaining.sort(key=lambda g: -g["student_count"])

            for course_group in remaining:
                scheduled = False

                # Determine preferred slot order for this group
                preferred_slots = []
                if course_group["courses"] and course_group["courses"][0]["groups"]:
                    first_gid = course_group["courses"][0]["groups"][0]
                    if first_gid in groups_dict:
                        gname = groups_dict[first_gid].group_name
                        if gname in group_preferences:
                            preferred_slots = group_preferences[gname].get(
                                "slots_order", []
                            )
                if not preferred_slots:
                    preferred_slots = [s["name"] for s in defined_time_slots]

                for current_date in dates:
                    if scheduled:
                        break
                    weekday = current_date.strftime("%A")

                    # Build allowed slots for this day
                    day_slots = preferred_slots[:]
                    if slots and current_date in slots_by_date:
                        cfg = slots_by_date[current_date]
                        cfg_names = set()
                        for s in cfg:
                            if isinstance(s, dict):
                                n = s.get("name") or s.get("label")
                                if n: cfg_names.add(n)
                            elif isinstance(s, (list, tuple)) and len(s) >= 2:
                                cfg_names.add(s[1])
                        if cfg_names:
                            day_slots = [s for s in day_slots if s in cfg_names]

                    if weekday in special_rules:
                        rule = special_rules[weekday]
                        if "allowed_slots" in rule:
                            day_slots = [
                                s for s in preferred_slots
                                if s in rule["allowed_slots"]
                            ]
                        elif rule.get("no_evening", False):
                            day_slots = [s for s in preferred_slots if s != "Evening"]

                    for slot_name in day_slots:
                        if scheduled:
                            break

                        # A. Capacity check
                        needed = course_group["student_count"]
                        if slot_seats_usage[current_date][slot_name] + needed > effective_seats:
                            continue

                        # B. Per-student constraint checks
                        group_student_ids = set()
                        for cd in course_group["courses"]:
                            for gid in cd["groups"]:
                                group_student_ids.update(
                                    enrollments_by_group.get(gid, set())
                                )

                        can_fit = True
                        for sid in group_student_ids:
                            day_slots_used = student_daily_exams[sid][current_date]

                            if len(day_slots_used) >= max_exams_per_day:
                                can_fit = False
                                break

                            if slot_name in day_slots_used and max_exams_per_slot <= 1:
                                can_fit = False
                                break

                            # FIX #8: O(log n) gap check using sorted list + bisect
                            if min_gap_days > 0 and _student_violates_gap(
                                student_sorted_dates[sid], current_date, min_gap_days
                            ):
                                can_fit = False
                                break

                        if not can_fit:
                            continue

                        # C. Create exams
                        for cd in course_group["courses"]:
                            c_id = cd["course_id"]
                            for gid in cd["groups"]:
                                g_obj = groups_dict[gid]
                                s_ids = enrollments_by_group.get(gid, set())

                                # Resolve slot times
                                st_time = en_time = None
                                if slots and current_date in slots_by_date:
                                    for s in slots_by_date[current_date]:
                                        sn = ss = se = None
                                        if isinstance(s, dict):
                                            sn = s.get("name") or s.get("label")
                                            ss = s.get("start") or s.get("start_time")
                                            se = s.get("end") or s.get("end_time")
                                        elif isinstance(s, (list, tuple)) and len(s) >= 4:
                                            sn, ss, se = s[1], s[2], s[3]
                                        if sn == slot_name and ss and se:
                                            st_time = (
                                                time(*map(int, ss.split(":")))
                                                if isinstance(ss, str) else ss
                                            )
                                            en_time = (
                                                time(*map(int, se.split(":")))
                                                if isinstance(se, str) else se
                                            )
                                            break

                                if not st_time:
                                    slot_def = next(
                                        (s for s in defined_time_slots
                                         if s["name"] == slot_name), None
                                    )
                                    if slot_def:
                                        st_time = time(*map(int, slot_def["start_time"].split(":")))
                                        en_time = time(*map(int, slot_def["end_time"].split(":")))

                                # Final fallback using central SLOT_MAP
                                if not st_time:
                                    st_time, en_time = SLOT_MAP.get(
                                        slot_name, (time(8, 0), time(11, 0))
                                    )

                                exam = Exam.objects.create(
                                    date=current_date,
                                    start_time=st_time,
                                    end_time=en_time,
                                    group=g_obj,
                                    slot_name=slot_name,
                                )
                                if master_timetable:
                                    master_timetable.exams.add(exam)
                                exams_created.append(exam)

                                ses = [
                                    StudentExam(student_id=sid, exam=exam)
                                    for sid in s_ids
                                ]
                                StudentExam.objects.bulk_create(ses)

                                # Update trackers
                                import bisect as _bisect
                                for sid in s_ids:
                                    student_daily_exams[sid][current_date].add(slot_name)
                                    _bisect.insort(student_sorted_dates[sid], current_date)
                                slot_seats_usage[current_date][slot_name] += len(s_ids)

                        scheduled = True
                        logger.info(
                            f"Scheduled {course_group['student_count']} students "
                            f"on {current_date} [{slot_name}]"
                        )

                if not scheduled:
                    unscheduled_groups.append(course_group)
                    for cd in course_group["courses"]:
                        for gid in cd["groups"]:
                            unscheduled_reasons[gid] = "No suitable slot found"

            # Step 6 — room allocation
            try:
                unaccommodated = allocate_shared_rooms(location)
            except Exception as exc:
                logger.error(f"Room allocation error: {exc}", exc_info=True)
                unaccommodated = []

        logger.info(
            f"Done: {len(exams_created)} exams created, "
            f"{len(unscheduled_groups)} groups unscheduled."
        )
        return exams_created, unaccommodated, unscheduled_groups, unscheduled_reasons

    except Exception as exc:
        logger.error(f"generate_exam_schedule failed: {exc}", exc_info=True)
        return [], [], [], {"error": str(exc)}