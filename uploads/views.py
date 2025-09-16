 

# from departments.models import Department
# from .models import RawEnrollmentsResource
# from rest_framework import generics
# from rest_framework import parsers
# from rest_framework.response import Response
# from rest_framework import status
# import pandas as pd
# from tablib import Dataset
# from student.models import Student
# from courses.models import Course, CourseGroup
# from enrollments.models import Enrollment
# from users.models import User
# from semesters.models import Semester
# from django.db import transaction
# from django.utils import timezone
# from django.contrib.auth.hashers import make_password
# from django.utils.crypto import get_random_string
# from collections import defaultdict

# def generate_unique_code():
#     return get_random_string(length=3)

# class ImportEnrollmentsData(generics.GenericAPIView):
#     parser_classes = [parsers.MultiPartParser]

#     def post(self, request, *args, **kwargs):
#         with transaction.atomic():
#             print(request.FILES)
#             file = request.FILES["myFile"]
#             df = pd.read_excel(file)

#             # Clean and prepare data
#             rename_columns = {
#                 "COURSECODE": "COURSECODE",
#                 "COURSENAME": "COURSENAME", 
#                 "CREDITS": "CREDITS",
#                 "GROUP": "GROUP",
#                 "STUDNUM": "STUDNUM",
#                 "STUDENTNAME": "STUDENTNAME",
#                 "FACULTYCODE": "FACULTYCODE",
#                 "TERM": "TERM",
#             }
#             df.rename(columns=rename_columns, inplace=True)
            
#             # Remove rows with NaN STUDNUM early
#             df = df.dropna(subset=['STUDNUM'])
            
#             # Convert STUDNUM to string early and filter valid ones
#             df['STUDNUM_STR'] = df['STUDNUM'].apply(lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) and x == int(x) else None)
#             df = df.dropna(subset=['STUDNUM_STR'])

#             # Get unique values
#             student_nums = df["STUDNUM_STR"].unique()
#             department_codes = df["FACULTYCODE"].dropna().unique()
#             course_codes = df["COURSECODE"].unique()
#             course_groups = df["GROUP"].unique()
#             semester_terms = df["TERM"].unique()

#             # Bulk fetch existing records to avoid repeated queries
#             existing_departments = {d.code: d for d in Department.objects.filter(code__in=department_codes)}
#             existing_semesters = {s.name: s for s in Semester.objects.filter(name__in=semester_terms)}
#             existing_students = {s.reg_no: s for s in Student.objects.filter(reg_no__in=student_nums).select_related('user')}
#             existing_courses = {c.code: c for c in Course.objects.filter(code__in=course_codes)}
#             existing_groups = {g.group_name: g for g in CourseGroup.objects.filter(group_name__in=course_groups).select_related('course')}
            
#             # Get existing users by email pattern for students
#             potential_emails = []
#             for _, row in df.iterrows():
#                 if pd.notna(row["STUDENTNAME"]) and pd.notna(row["STUDNUM_STR"]):
#                     name_parts = str(row["STUDENTNAME"]).split()
#                     first_name = name_parts[0]
#                     last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
#                     email = f"{''.join([first_name.lower(), last_name.lower(), row['STUDNUM_STR']])}@auca.ac.rw".replace(" ", "")
#                     potential_emails.append(email)
            
#             existing_users = {u.email: u for u in User.objects.filter(email__in=potential_emails)}

#             # Bulk create departments
#             departments_to_create = []
#             for code in department_codes:
#                 if pd.isna(code):
#                     continue
#                 code_str = str(int(code)) if isinstance(code, float) and code == int(code) else str(code)
#                 if code_str not in existing_departments:
#                     departments_to_create.append(Department(
#                         code=code_str,
#                         name=code_str,
#                         location_id=1 if code_str in ["15", "12", "19"] else 2,
#                     ))
            
#             if departments_to_create:
#                 Department.objects.bulk_create(departments_to_create, ignore_conflicts=True)
#                 # Refresh existing_departments
#                 existing_departments.update({d.code: d for d in Department.objects.filter(code__in=department_codes)})

#             # Bulk create/update semesters
#             semesters_to_create = []
#             semesters_to_update = []
#             for term in semester_terms:
#                 if term in existing_semesters:
#                     semester = existing_semesters[term]
#                     semester.name = term
#                     semesters_to_update.append(semester)
#                 else:
#                     semesters_to_create.append(Semester(
#                         name=term,
#                         start_date=timezone.now(),
#                         end_date=timezone.now()
#                     ))
            
#             if semesters_to_create:
#                 Semester.objects.bulk_create(semesters_to_create, ignore_conflicts=True)
#             if semesters_to_update:
#                 Semester.objects.bulk_update(semesters_to_update, ['name'])
            
#             # Refresh existing_semesters
#             existing_semesters.update({s.name: s for s in Semester.objects.filter(name__in=semester_terms)})

#             # Process students - create users and students
#             users_to_create = []
#             users_to_update = []
#             students_to_create = []
            
#             # Group data by student for efficient processing
#             student_data = df.groupby('STUDNUM_STR').first().reset_index()
            
#             for _, row in student_data.iterrows():
#                 reg_no = row['STUDNUM_STR']
#                 student_name = row["STUDENTNAME"]
                
#                 if pd.isna(student_name):
#                     continue
                    
#                 name_parts = str(student_name).split()
#                 first_name = name_parts[0]
#                 last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
#                 email = f"{''.join([first_name.lower(), last_name.lower(), reg_no])}@auca.ac.rw".replace(" ", "")
                
#                 existing_student = existing_students.get(reg_no)
                
#                 if existing_student:
#                     # Update existing user
#                     user = existing_student.user
#                     user.first_name = first_name
#                     user.last_name = last_name
#                     user.email = email
#                     users_to_update.append(user)
#                 else:
#                     # Create new user and student
#                     existing_user = existing_users.get(email)
#                     if not existing_user:
#                         user = User(
#                             email=email,
#                             first_name=first_name,
#                             last_name=last_name,
#                             role="student",
#                             password=make_password("password123."),
#                             is_active=True,
#                         )
#                         users_to_create.append(user)
#                     else:
#                         existing_user.first_name = first_name
#                         existing_user.last_name = last_name
#                         existing_user.email = email
#                         users_to_update.append(existing_user)
#                         user = existing_user
                    
#                     # Prepare student for creation (will be created after users)
#                     faculty_code = row["FACULTYCODE"]
#                     department = existing_departments.get(str(int(faculty_code)) if isinstance(faculty_code, float) and faculty_code == int(faculty_code) else str(faculty_code))
#                     if department:
#                         students_to_create.append({
#                             'user_email': email,
#                             'reg_no': reg_no,
#                             'department': department,
#                         })

#             # Bulk create/update users
#             if users_to_create:
#                 User.objects.bulk_create(users_to_create, ignore_conflicts=True)
#             if users_to_update:
#                 User.objects.bulk_update(users_to_update, ['first_name', 'last_name', 'email'])

#             # Now create students (need to get user IDs first)
#             if students_to_create:
#                 # Get all users again to have the IDs
#                 all_users = {u.email: u for u in User.objects.filter(email__in=[s['user_email'] for s in students_to_create])}
#                 students_bulk_create = []
#                 for student_data in students_to_create:
#                     user = all_users.get(student_data['user_email'])
#                     if user:
#                         students_bulk_create.append(Student(
#                             user=user,
#                             reg_no=student_data['reg_no'],
#                             department=student_data['department'],
#                         ))
                
#                 if students_bulk_create:
#                     Student.objects.bulk_create(students_bulk_create, ignore_conflicts=True)

#             # Refresh students
#             existing_students.update({s.reg_no: s for s in Student.objects.filter(reg_no__in=student_nums).select_related('user')})

#             # Bulk create courses
#             courses_to_create = []
#             course_data = df.groupby('COURSECODE').first().reset_index()
            
#             for _, row in course_data.iterrows():
#                 code = row['COURSECODE']
#                 if code not in existing_courses:
#                     term_value = row["TERM"]
#                     semester = existing_semesters.get(term_value)
#                     department_code = str(int(row["FACULTYCODE"])) if isinstance(row["FACULTYCODE"], float) and row["FACULTYCODE"] == int(row["FACULTYCODE"]) else str(row["FACULTYCODE"])
#                     department = existing_departments.get(department_code)
                    
#                     if semester and department:
#                         courses_to_create.append(Course(
#                             code=code,
#                             title=row["COURSENAME"],
#                             credits=row["CREDITS"],
#                             semester=semester,
#                             department=department,
#                         ))

#             if courses_to_create:
#                 Course.objects.bulk_create(courses_to_create, ignore_conflicts=True)
#                 # Refresh existing_courses
#                 existing_courses.update({c.code: c for c in Course.objects.filter(code__in=course_codes)})

#             # Bulk create course groups
#             groups_to_create = []
#             groups_to_update = []
#             group_data = df.groupby('GROUP').first().reset_index()
            
#             for _, row in group_data.iterrows():
#                 group = row['GROUP']
#                 course_code = row["COURSECODE"]
#                 course = existing_courses.get(course_code)
                
#                 if course:
#                     if group in existing_groups:
#                         existing_group = existing_groups[group]
#                         if existing_group.course != course:
#                             existing_group.course = course
#                             groups_to_update.append(existing_group)
#                     else:
#                         groups_to_create.append(CourseGroup(
#                             group_name=group,
#                             course=course,
#                         ))

#             if groups_to_create:
#                 CourseGroup.objects.bulk_create(groups_to_create, ignore_conflicts=True)
#             if groups_to_update:
#                 CourseGroup.objects.bulk_update(groups_to_update, ['course'])

#             # Refresh existing_groups
#             existing_groups.update({g.group_name: g for g in CourseGroup.objects.filter(group_name__in=course_groups).select_related('course')})

#             # Bulk create enrollments
#             existing_enrollments = {}
#             for enrollment in Enrollment.objects.filter(
#                 student__reg_no__in=student_nums,
#                 course__code__in=course_codes
#             ).select_related('student', 'course', 'group'):
#                 key = (enrollment.student.reg_no, enrollment.course.code)
#                 existing_enrollments[key] = enrollment

#             enrollments_to_create = []
#             enrollments_to_update = []
            
#             for _, row in df.iterrows():
#                 student_reg_no = row['STUDNUM_STR']
#                 course_code = row["COURSECODE"]
#                 group_name = row["GROUP"]

#                 student = existing_students.get(student_reg_no)
#                 course = existing_courses.get(course_code)
#                 group = existing_groups.get(group_name)

#                 if student and course and group:
#                     enrollment_key = (student_reg_no, course_code)
#                     existing_enrollment = existing_enrollments.get(enrollment_key)
                    
#                     if not existing_enrollment:
#                         enrollments_to_create.append(Enrollment(
#                             student=student,
#                             course=course,
#                             group=group,
#                         ))
#                     else:
#                         if existing_enrollment.group != group:
#                             existing_enrollment.group = group
#                             enrollments_to_update.append(existing_enrollment)

#             if enrollments_to_create:
#                 Enrollment.objects.bulk_create(enrollments_to_create, ignore_conflicts=True)
#             if enrollments_to_update:
#                 Enrollment.objects.bulk_update(enrollments_to_update, ['group'])

#             return Response({"status": "Student Data Imported Successfully"})




from departments.models import Department
from .models import RawEnrollmentsResource
from rest_framework import generics
from rest_framework import parsers
from rest_framework.response import Response
from rest_framework import status
import pandas as pd
from tablib import Dataset
from student.models import Student
from courses.models import Course, CourseGroup
from enrollments.models import Enrollment
from users.models import User
from semesters.models import Semester
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

def generate_unique_code():
    return get_random_string(length=3)

class ImportEnrollmentsData(generics.GenericAPIView):
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            print(request.FILES)
            file = request.FILES["myFile"]
            df = pd.read_excel(file)

            # Clean and prepare data
            rename_columns = {
                "COURSECODE": "COURSECODE",
                "COURSENAME": "COURSENAME", 
                "CREDITS": "CREDITS",
                "GROUP": "GROUP",
                "STUDNUM": "STUDNUM",
                "STUDENTNAME": "STUDENTNAME",
                "FACULTYCODE": "FACULTYCODE",
                "TERM": "TERM",
            }
            df.rename(columns=rename_columns, inplace=True)
            
            # Remove rows with NaN STUDNUM early
            df = df.dropna(subset=['STUDNUM'])
            
            # Convert STUDNUM to string early and filter valid ones
            df['STUDNUM_STR'] = df['STUDNUM'].apply(lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) and x == int(x) else None)
            df = df.dropna(subset=['STUDNUM_STR'])

            # Get unique values
            student_nums = df["STUDNUM_STR"].unique()
            department_codes = df["FACULTYCODE"].dropna().unique()
            course_codes = df["COURSECODE"].unique()
            # FIXED: Get unique (course, group) combinations instead of just groups
            course_groups = df[["COURSECODE", "GROUP"]].drop_duplicates()
            semester_terms = df["TERM"].unique()

            # Bulk fetch existing records to avoid repeated queries
            existing_departments = {d.code: d for d in Department.objects.filter(code__in=department_codes)}
            existing_semesters = {s.name: s for s in Semester.objects.filter(name__in=semester_terms)}
            existing_students = {s.reg_no: s for s in Student.objects.filter(reg_no__in=student_nums).select_related('user')}
            existing_courses = {c.code: c for c in Course.objects.filter(code__in=course_codes)}
            
            # FIXED: Fetch existing groups with course relationship for proper matching
            unique_group_names = course_groups["GROUP"].unique()
            existing_groups = {}
            for g in CourseGroup.objects.filter(group_name__in=unique_group_names).select_related('course'):
                key = (g.course.code, g.group_name)  # Key by (course_code, group_name)
                existing_groups[key] = g
            
            # Get existing users by email pattern for students
            potential_emails = []
            for _, row in df.iterrows():
                if pd.notna(row["STUDENTNAME"]) and pd.notna(row["STUDNUM_STR"]):
                    name_parts = str(row["STUDENTNAME"]).split()
                    first_name = name_parts[0]
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                    email = f"{''.join([first_name.lower(), last_name.lower(), row['STUDNUM_STR']])}@auca.ac.rw".replace(" ", "")
                    potential_emails.append(email)
            
            existing_users = {u.email: u for u in User.objects.filter(email__in=potential_emails)}

            # Bulk create departments
            departments_to_create = []
            for code in department_codes:
                if pd.isna(code):
                    continue
                code_str = str(int(code)) if isinstance(code, float) and code == int(code) else str(code)
                if code_str not in existing_departments:
                    departments_to_create.append(Department(
                        code=code_str,
                        name=code_str,
                        location_id=1 if code_str in ["15", "12", "19"] else 2,
                    ))
            
            if departments_to_create:
                Department.objects.bulk_create(departments_to_create, ignore_conflicts=True)
                # Refresh existing_departments
                existing_departments.update({d.code: d for d in Department.objects.filter(code__in=department_codes)})

            # Bulk create/update semesters
            semesters_to_create = []
            semesters_to_update = []
            for term in semester_terms:
                if term in existing_semesters:
                    semester = existing_semesters[term]
                    semester.name = term
                    semesters_to_update.append(semester)
                else:
                    semesters_to_create.append(Semester(
                        name=term,
                        start_date=timezone.now(),
                        end_date=timezone.now()
                    ))
            
            if semesters_to_create:
                Semester.objects.bulk_create(semesters_to_create, ignore_conflicts=True)
            if semesters_to_update:
                Semester.objects.bulk_update(semesters_to_update, ['name'])
            
            # Refresh existing_semesters
            existing_semesters.update({s.name: s for s in Semester.objects.filter(name__in=semester_terms)})

            # Process students - create users and students
            users_to_create = []
            users_to_update = []
            students_to_create = []
            
            # Group data by student for efficient processing
            student_data = df.groupby('STUDNUM_STR').first().reset_index()
            
            for _, row in student_data.iterrows():
                reg_no = row['STUDNUM_STR']
                student_name = row["STUDENTNAME"]
                
                if pd.isna(student_name):
                    continue
                    
                name_parts = str(student_name).split()
                first_name = name_parts[0]
                last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                email = f"{''.join([first_name.lower(), last_name.lower(), reg_no])}@auca.ac.rw".replace(" ", "")
                
                existing_student = existing_students.get(reg_no)
                
                if existing_student:
                    # Update existing user
                    user = existing_student.user
                    user.first_name = first_name
                    user.last_name = last_name
                    user.email = email
                    users_to_update.append(user)
                else:
                    # Create new user and student
                    existing_user = existing_users.get(email)
                    if not existing_user:
                        user = User(
                            email=email,
                            first_name=first_name,
                            last_name=last_name,
                            role="student",
                            password=make_password("password123."),
                            is_active=True,
                        )
                        users_to_create.append(user)
                    else:
                        existing_user.first_name = first_name
                        existing_user.last_name = last_name
                        existing_user.email = email
                        users_to_update.append(existing_user)
                        user = existing_user
                    
                    # Prepare student for creation (will be created after users)
                    faculty_code = row["FACULTYCODE"]
                    department = existing_departments.get(str(int(faculty_code)) if isinstance(faculty_code, float) and faculty_code == int(faculty_code) else str(faculty_code))
                    if department:
                        students_to_create.append({
                            'user_email': email,
                            'reg_no': reg_no,
                            'department': department,
                        })

            # Bulk create/update users
            if users_to_create:
                User.objects.bulk_create(users_to_create, ignore_conflicts=True)
            if users_to_update:
                User.objects.bulk_update(users_to_update, ['first_name', 'last_name', 'email'])

            # Now create students (need to get user IDs first)
            if students_to_create:
                # Get all users again to have the IDs
                all_users = {u.email: u for u in User.objects.filter(email__in=[s['user_email'] for s in students_to_create])}
                students_bulk_create = []
                for student_data in students_to_create:
                    user = all_users.get(student_data['user_email'])
                    if user:
                        students_bulk_create.append(Student(
                            user=user,
                            reg_no=student_data['reg_no'],
                            department=student_data['department'],
                        ))
                
                if students_bulk_create:
                    Student.objects.bulk_create(students_bulk_create, ignore_conflicts=True)

            # Refresh students
            existing_students.update({s.reg_no: s for s in Student.objects.filter(reg_no__in=student_nums).select_related('user')})

            # Bulk create courses
            courses_to_create = []
            course_data = df.groupby('COURSECODE').first().reset_index()
            
            for _, row in course_data.iterrows():
                code = row['COURSECODE']
                if code not in existing_courses:
                    term_value = row["TERM"]
                    semester = existing_semesters.get(term_value)
                    department_code = str(int(row["FACULTYCODE"])) if isinstance(row["FACULTYCODE"], float) and row["FACULTYCODE"] == int(row["FACULTYCODE"]) else str(row["FACULTYCODE"])
                    department = existing_departments.get(department_code)
                    
                    if semester and department:
                        courses_to_create.append(Course(
                            code=code,
                            title=row["COURSENAME"],  # Fixed: use course_name instead of title
                            credits=row["CREDITS"],
                            semester=semester,
                            department=department,
                        ))

            if courses_to_create:
                Course.objects.bulk_create(courses_to_create, ignore_conflicts=True)
                # Refresh existing_courses
                existing_courses.update({c.code: c for c in Course.objects.filter(code__in=course_codes)})

            # FIXED: Bulk create course groups using (course, group) combinations
            groups_to_create = []
            groups_to_update = []
            
            # Track potential conflicts for logging
            group_conflicts = defaultdict(set)
            
            for _, row in course_groups.iterrows():
                course_code = row['COURSECODE']
                group_name = row['GROUP']
                course = existing_courses.get(course_code)
                
                if course:
                    group_key = (course_code, group_name)
                    existing_group = existing_groups.get(group_key)
                    
                    # Check for conflicts: same group name with different courses
                    for existing_key, existing_group_obj in existing_groups.items():
                        if existing_group_obj.group_name == group_name and existing_key[0] != course_code:
                            group_conflicts[group_name].add(existing_key[0])
                            group_conflicts[group_name].add(course_code)
                    
                    if not existing_group:
                        # Check if group name already exists with different course
                        conflicting_groups = [g for g in existing_groups.values() if g.group_name == group_name and g.course != course]
                        
                        if conflicting_groups:
                            # Create a unique group name to avoid conflicts
                            unique_group_name = f"{group_name}_{course_code}"
                            logger.warning(f"Group name conflict detected: {group_name} exists for multiple courses. Creating unique name: {unique_group_name}")
                            groups_to_create.append(CourseGroup(
                                group_name=unique_group_name,
                                course=course,
                            ))
                            # Update our tracking with the new unique name
                            existing_groups[(course_code, unique_group_name)] = None  # Placeholder
                        else:
                            groups_to_create.append(CourseGroup(
                                group_name=group_name,
                                course=course,
                            ))
                    else:
                        # Group exists with correct course, no action needed
                        if existing_group.course != course:
                            logger.warning(f"Group {group_name} exists but belongs to different course. Expected: {course_code}, Found: {existing_group.course.code}")

            # Log conflicts for manual review
            if group_conflicts:
                logger.warning("Group name conflicts detected:")
                for group_name, courses in group_conflicts.items():
                    logger.warning(f"  Group '{group_name}' appears in courses: {list(courses)}")

            if groups_to_create:
                CourseGroup.objects.bulk_create(groups_to_create, ignore_conflicts=True)

            # FIXED: Refresh existing_groups with proper (course_code, group_name) keys
            existing_groups = {}
            for g in CourseGroup.objects.filter(
                course__code__in=course_codes,
                group_name__in=list(course_groups["GROUP"].unique()) + [f"{gn}_{cc}" for cc in course_codes for gn in course_groups["GROUP"].unique()]
            ).select_related('course'):
                key = (g.course.code, g.group_name)
                existing_groups[key] = g

            # FIXED: Bulk create enrollments with proper group matching
            existing_enrollments = {}
            for enrollment in Enrollment.objects.filter(
                student__reg_no__in=student_nums,
                course__code__in=course_codes
            ).select_related('student', 'course', 'group'):
                key = (enrollment.student.reg_no, enrollment.course.code)
                existing_enrollments[key] = enrollment

            enrollments_to_create = []
            enrollments_to_update = []
            enrollment_errors = []
            
            for _, row in df.iterrows():
                student_reg_no = row['STUDNUM_STR']
                course_code = row["COURSECODE"]
                group_name = row["GROUP"]

                student = existing_students.get(student_reg_no)
                course = existing_courses.get(course_code)
                
                # FIXED: Look for group using (course_code, group_name) key
                group = existing_groups.get((course_code, group_name))
                
                # If not found, try with the unique naming pattern
                if not group:
                    unique_group_name = f"{group_name}_{course_code}"
                    group = existing_groups.get((course_code, unique_group_name))

                if student and course:
                    enrollment_key = (student_reg_no, course_code)
                    existing_enrollment = existing_enrollments.get(enrollment_key)
                    
                    if not existing_enrollment:
                        if group:
                            enrollments_to_create.append(Enrollment(
                                student=student,
                                course=course,
                                group=group,
                            ))
                        else:
                            # Create enrollment without group if group not found
                            enrollments_to_create.append(Enrollment(
                                student=student,
                                course=course,
                                group=None,
                            ))
                            enrollment_errors.append(f"Group '{group_name}' not found for course '{course_code}' - enrollment created without group")
                    else:
                        # Update existing enrollment with correct group
                        if group and existing_enrollment.group != group:
                            existing_enrollment.group = group
                            enrollments_to_update.append(existing_enrollment)
                        elif not group and existing_enrollment.group:
                            # Clear invalid group assignment
                            existing_enrollment.group = None
                            enrollments_to_update.append(existing_enrollment)
                            enrollment_errors.append(f"Cleared invalid group assignment for student {student_reg_no} in course {course_code}")

            if enrollments_to_create:
                Enrollment.objects.bulk_create(enrollments_to_create, ignore_conflicts=True)
            if enrollments_to_update:
                Enrollment.objects.bulk_update(enrollments_to_update, ['group'])

            # Log any enrollment errors for review
            if enrollment_errors:
                logger.warning("Enrollment issues detected:")
                for error in enrollment_errors[:10]:  # Log first 10 errors
                    logger.warning(f"  {error}")
                if len(enrollment_errors) > 10:
                    logger.warning(f"  ... and {len(enrollment_errors) - 10} more issues")

            response_message = "Student Data Imported Successfully"
            if group_conflicts or enrollment_errors:
                response_message += f" (with {len(group_conflicts)} group conflicts and {len(enrollment_errors)} enrollment issues - check logs)"

            return Response({"status": response_message})