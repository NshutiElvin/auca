from django.test import TestCase
from datetime import date, time, timedelta
from schedules.utils import (
    which_suitable_slot_to_schedule_course_group,
    allocate_shared_rooms,
    find_compatible_courses_within_group
)
from courses.models import Course, CourseGroup
from departments.models import Department
from rooms.models import Room, Location
from exams.models import Exam, StudentExam
from student.models import Student
from users.models import User
from enrollments.models import Enrollment
from semesters.models import Semester
import logging

# Disable logging during tests to keep output clean
logging.disable(logging.CRITICAL)

class SchedulerLogicTests(TestCase):
    def setUp(self):
        # Create Locations
        self.loc_main = Location.objects.create(name="Main Campus")
        self.loc_city = Location.objects.create(name="City Campus")

        # Create Departments (linked to Locations)
        self.dept_main = Department.objects.create(name="CS", code="CS", location=self.loc_main)
        self.dept_city = Department.objects.create(name="Business", code="BUS", location=self.loc_city)

        # Create Semesters (needed for Courses)
        self.semester = Semester.objects.create(name="Sem 1", start_date=date(2025, 1, 1), end_date=date(2025, 6, 1))

        # Create Courses
        self.course_main = Course.objects.create(title="Intro CS", code="CS101", department=self.dept_main, semester=self.semester)
        self.course_city = Course.objects.create(title="Intro Biz", code="BUS101", department=self.dept_city, semester=self.semester)

        # Create Groups
        self.group_main = CourseGroup.objects.create(course=self.course_main, group_name="A")
        self.group_city = CourseGroup.objects.create(course=self.course_city, group_name="B")

        # Create Rooms
        # Main Campus has 0 capacity (FULL)
        # City Campus has 100 capacity (EMPTY)
        self.room_city = Room.objects.create(name="City Hall", capacity=100, location=self.loc_city)
        # Main campus room is tiny or non-existent for this test
        self.room_main_tiny = Room.objects.create(name="Main Tiny", capacity=0, location=self.loc_main) 

        # Create Students
        self.user1 = User.objects.create(email="john@example.com", first_name="John", last_name="Doe", role="student")
        self.student1 = Student.objects.create(user=self.user1, reg_no="123")
        
    def test_location_aware_capacity(self):
        """
        Test that scheduling checks capacity ONLY for the course's location.
        Scenario: 
        - Course is at Main Campus (Capacity 0).
        - City Campus has Capacity 100.
        - Global Capacity is 100.
        - Old Buggy Logic: distinct locations ignored -> Would assert VALID (because 100 available globally).
        - New Fixed Logic: Should assert INVALID (because Main Campus has 0 capacity).
        """
        # Enroll student in Main Campus course
        Enrollment.objects.create(student=self.student1, course=self.course_main, group=self.group_main)
        
        target_date = date(2025, 1, 1) # Future date
        new_group_ids = [self.group_main.id]
        
        # Act
        _, best_suggestion, _, conflicts = which_suitable_slot_to_schedule_course_group(
            target_date, new_group_ids, "Morning"
        )
        
        # Assert
        # Should NOT find a suitable slot because Main Campus has 0 capacity check
        # The 'conflicts' dict or 'best_suggestion' should reflect failure.
        
        # If best_suggestion is None or reflects failure, PASS.
        # Check reasons in conflicts if present
        
        self.assertIsNone(best_suggestion, "Should not return a suggestion if local capacity is insufficient")
        
        # Verify specific error in conflicts
        found_capacity_error = False
        for error_list in conflicts.values():
            for error in error_list:
                if "lacks room capacity" in str(error) and "Main Campus" in str(error):
                    found_capacity_error = True
        
        self.assertTrue(found_capacity_error, "Should report insufficient rooms specifically for Main Campus")

    def test_conflict_detection_optimized(self):
        """
        Test that student conflicts are correctly detected.
        """
        target_date = date(2025, 1, 2)
        slot = "Morning"

        # 1. Schedule an exam for Student 1 in City Campus (Group B)
        enrollment_city = Enrollment.objects.create(student=self.student1, course=self.course_city, group=self.group_city)
        exam_city = Exam.objects.create(
            date=target_date, 
            slot_name=slot, 
            group=self.group_city,
            start_time=time(8,0), 
            end_time=time(11,0)
        )
        StudentExam.objects.create(student=self.student1, exam=exam_city)

        # 2. Try to schedule Main Campus Group A (which Student 1 is also in)
        # Note: We need a room in Main Campus now to pass capacity check
        self.room_main_tiny.capacity = 100
        self.room_main_tiny.save()
        
        Enrollment.objects.create(student=self.student1, course=self.course_main, group=self.group_main)
        
        # Act
        new_group_ids = [self.group_main.id]
        _, best_suggestion, suggestions, conflicts = which_suitable_slot_to_schedule_course_group(
            target_date, new_group_ids, slot
        )
        
        # Assert
        # The 'Morning' slot specific suggestion should be False
        morning_suggestion = next((s for s in suggestions if s["slot"] == "Morning" and s["date"] == target_date), None)
        
        self.assertIsNotNone(morning_suggestion)
        self.assertFalse(morning_suggestion["suggested"], "Morning slot should be rejected due to conflict")
        self.assertTrue("conflicts" in morning_suggestion["reason"], "Reason should mention conflicts")

    def test_allocate_shared_rooms_fragmentation_fix(self):
        """
        Verify that allocate_shared_rooms fills rooms completely (fragmentation fix).
        """
        # Create room with capacity 100 at Main Campus
        self.room_city.delete() # Ignore city
        self.room_main_tiny.capacity = 100
        self.room_main_tiny.save()

        # Create 4 exams of size 25 each (Total 100) -> Should all fit in 1 room
        # Old logic stopped after first pair? Or left gaps.
        
        exams = []
        for i in range(4):
            c = Course.objects.create(title=f"Course {i}", code=f"C{i}", department=self.dept_main, semester=self.semester)
            g = CourseGroup.objects.create(course=c, group_name="A")
            e = Exam.objects.create(date=date(2025, 1, 3), slot_name="Morning", group=g, start_time=time(8,0), end_time=time(11,0))
            exams.append(e)
            
            # Enroll 25 students in each
            for s_idx in range(25):
                u = User.objects.create(email=f"s{i}_{s_idx}@example.com", first_name=f"S{i}", last_name=f"{s_idx}", role="student")
                s = Student.objects.create(user=u, reg_no=f"{i}-{s_idx}")
                StudentExam.objects.create(student=s, exam=e, room=None) # Unassigned

        # Act
        unaccommodated = allocate_shared_rooms(self.loc_main.id)

        # Assert
        self.assertEqual(len(unaccommodated), 0, "All students should be assigned")
        
        # Verify usage of room
        # All 100 students should be in room_main_tiny
        assigned_count = StudentExam.objects.filter(room=self.room_main_tiny).count()
        self.assertEqual(assigned_count, 100, "Room should be fully utilized")

    def test_find_compatible_courses_group_size(self):
        """
        Verify that course grouping uses SINGLE slot capacity (total_seats) not Daily capacity.
        """
        # Capacity is 100 (from room_main_tiny setup for this test, let's ensure it)
        try:
            total_seats = Room.objects.filter(location_id=self.loc_main.id).aggregate(total=lambda x: x)["total"]
        except:
            total_seats = 100 # Mock if needed or rely on DB
        
        self.room_main_tiny.capacity = 100
        self.room_main_tiny.save()
        
        # Create 2 courses of size 60 each. 
        # Total 120. > 100 (Single Slot). < 300 (Daily).
        # Old Logic: Would Group them together (1 Group).
        # New Logic: Should Split them (2 Groups) because 120 > 100.
        
        c1 = Course.objects.create(title="Split1", code="S1", department=self.dept_main, semester=self.semester)
        group1 = CourseGroup.objects.create(course=c1, group_name="A")
        # Enroll 60
        for i in range(60):
            u = User.objects.create(email=f"a{i}@example.com", first_name="A", last_name=str(i), role="student")
            s = Student.objects.create(user=u, reg_no=f"A{i}")
            Enrollment.objects.create(student=s, course=c1, group=group1)

        c2 = Course.objects.create(title="Split2", code="S2", department=self.dept_main, semester=self.semester)
        group2 = CourseGroup.objects.create(course=c2, group_name="A")
        # Enroll 60
        for i in range(60):
            u = User.objects.create(email=f"b{i}@example.com", first_name="B", last_name=str(i), role="student")
            s = Student.objects.create(user=u, reg_no=f"B{i}")
            Enrollment.objects.create(student=s, course=c2, group=group2)

        # Act
        compatible_groups, _ = find_compatible_courses_within_group([c1.id, c2.id])
        
        # Assert
        # Should return 2 groups because 60+60=120 > 100
        self.assertEqual(len(compatible_groups), 2, "Courses should be split into 2 groups due to single-slot capacity constraint")

    def test_suggest_slot_for_unscheduled_group(self):
        """
        Verify that which_suitable_slot_to_schedule_course_group correctly suggests a slot
        when the timetable is already partially populated.
        Scenario:
        - Timetable exists.
        - Morning slot is FULL/CONFLICTED for a student.
        - Afternoon slot is FREE.
        - Function should return 'Afternoon' as a suggestion.
        """
        target_date = date(2025, 1, 10)  # Middle of January
        
        # IMPORTANT: The function needs existing exams to establish min/max date range
        # Create exams before and after target_date to ensure it's in range
        early_exam = Exam.objects.create(
            date=date(2025, 1, 5),
            slot_name="Morning",
            group=self.group_city,
            start_time=time(8,0),
            end_time=time(11,0)
        )
        late_exam = Exam.objects.create(
            date=date(2025, 1, 15),
            slot_name="Afternoon",
            group=self.group_city,
            start_time=time(13,0),
            end_time=time(16,0)
        )
        
        # 1. Create a conflict in Morning Slot for student1 ON THE TARGET DATE
        # Student1 is in course_city (Group B)
        Enrollment.objects.create(student=self.student1, course=self.course_city, group=self.group_city)
        exam_conflict = Exam.objects.create(
            date=target_date, 
            slot_name="Morning", 
            group=self.group_city,
            start_time=time(8,0), 
            end_time=time(11,0)
        )
        StudentExam.objects.create(student=self.student1, exam=exam_conflict)
        
        # 2. Try to schedule course_main (Group A) for Student1
        # This new group should NOT fit in Morning (conflict)
        Enrollment.objects.create(student=self.student1, course=self.course_main, group=self.group_main)
        
        # Ensure room capacity exists at Main Campus for the test
        self.room_main_tiny.capacity = 100
        self.room_main_tiny.save()
        
        # Act: Ask for suggestion for Morning (should fail) and generally
        _, best_suggestion, suggestions, conflicts = which_suitable_slot_to_schedule_course_group(
            target_date, [self.group_main.id], "Morning"
        )
        
        # Assert
        # The function should return a best_suggestion that is NOT None
        self.assertIsNotNone(best_suggestion, "Function should suggest at least one valid slot")
        
        # The best suggestion should NOT be Morning (which has a conflict)
        # It should be Afternoon or Evening (both free)
        self.assertIn(best_suggestion["slot"], ["Afternoon", "Evening"], 
                     "Best suggestion should be a free slot (Afternoon or Evening), not the conflicted Morning")
        
        # Verify the best suggestion is on the target date
        self.assertEqual(best_suggestion["date"], target_date, "Best suggestion should be on the target date")
        
        # Verify conflicts were detected for Morning
        has_conflicts = any(len(conflict_list) > 0 for conflict_list in conflicts.values())
        self.assertTrue(has_conflicts, "Should have detected at least one conflict (Morning slot)")
