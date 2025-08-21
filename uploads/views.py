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

def generate_unique_code():
        return get_random_string(length=3)

class ImportEnrollmentsData(generics.GenericAPIView):
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, *args, **kwargs):
       with transaction.atomic():
            print(request.FILES)
            file = request.FILES["myFile"]
            df = pd.read_excel(file)

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
            students_num = df["STUDNUM"].unique()
            departments = df["FACULTYCODE"].unique()
            courses = df["COURSECODE"].unique()
            course_groups = df["GROUP"].unique()
            semesters = df["TERM"].unique()
            for code in departments:
                if pd.isna(code):
                    continue  # Skip if FACULTYCODE is NaN
                code_str = str(int(code)) if isinstance(code, float) and code.is_integer() else str(code)
                existing_department = Department.objects.filter(code=code_str).first()
                if not existing_department:
                    Department.objects.create(
                        code=code_str,
                        name=code_str,
                        location_id=1 if code_str in ["15", "12", "19"] else 2,
                    )
            for term in semesters:
                existing_semester = Semester.objects.filter(name=term).first()
                if not existing_semester:
                    Semester.objects.create(name=term, start_date= timezone.now() , end_date=timezone.now())
                else:
                    # Optionally update the semester name, but do not set start_date or end_date to None
                    existing_semester.name = term
                    existing_semester.save()

            for stu in students_num:
                if pd.isna(stu):
                    continue  # Skip if STUDNUM is NaN
                try:
                    reg_no = str(int(stu))
                except (ValueError, TypeError):
                    continue  # Skip if conversion fails
                existing_student = Student.objects.filter(reg_no=reg_no).first()
                if existing_student:
                    student_name = df[df["STUDNUM"] == stu]["STUDENTNAME"].values[0]
                    if isinstance(student_name, str):
                        name_parts = student_name.split()
                    else:
                        name_parts = [str(student_name)]
                    first_name = name_parts[0]
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                    user = User.objects.filter(id=existing_student.user.id).first()
                    if not user:
                        user = User.objects.filter(email="".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ","")).first()
                        if not user:
                            user = User.objects.create(
                                email="".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ",""),
                                first_name=first_name,
                                last_name=last_name,
                                role="student",
                                password=make_password("password123."),
                                is_active=True,
                            )
                        else:
                            user.first_name = first_name
                            user.last_name = last_name
                            user.email="".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ","")
                            user.save()
                    else:
                        user.first_name = first_name
                        user.last_name = last_name
                        user.email="".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ","")
                        user.save()
                else:
                    student_row = df[df["STUDNUM"] == stu]
                    student_name = student_row["STUDENTNAME"].values[0] if not student_row.empty else ""
                    user = User.objects.filter(email=reg_no).first()
                    if not user:
                        user = User.objects.create(
                            email= "".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ",""),
                            first_name=first_name,
                            last_name=last_name,
                            role="student",
                            password=make_password("password123."),
                            is_active=True,
                        )
                        user.first_name = first_name
                        user.last_name = last_name
                        user.email="".join([first_name.lower(), last_name.lower(), reg_no])+"@auca.ac.rw".replace(" ","")
                        user.save()
                    existing_department = Department.objects.filter(
                        code=df[df["STUDNUM"] == stu]["FACULTYCODE"].values[0]
                    ).first()
                    if not existing_department:
                        existing_department = Department.objects.create(
                            code=df[df["STUDNUM"] == stu]["FACULTYCODE"].values[0],
                            name=df[df["STUDNUM"] == stu]["FACULTYCODE"].values[0],
                            location_id=(
                                1
                                if df[df["STUDNUM"] == stu]["FACULTYCODE"].values[0]
                                in ["15", "12", "19"]
                                else 2
                            ),
                        )
                    existing_student = Student.objects.create(
                        user=user,
                        reg_no=reg_no,
                         
                        department=existing_department,
                      )
            for code in courses:
                print(code)
                existing_course = Course.objects.filter(code=code).first()
                if not existing_course:
                    course_rows = df[df["COURSECODE"] == code]
                    if course_rows.empty:
                        continue  # Skip if no matching course row
                    term_value = course_rows["TERM"].values[0]
                    semester = Semester.objects.filter(
                        name=term_value
                    ).first()
                    if not semester:
                        semester = Semester.objects.create(
                            name=term_value,
                            start_date=None,
                            end_date=None,
                        )
                    department_code = course_rows["FACULTYCODE"].values[0]
                    department = Department.objects.filter(code=department_code).first()
                    Course.objects.create(
                        code=code,
                        title=course_rows["COURSENAME"].values[0],
                        credits=course_rows["CREDITS"].values[0],
                        semester=semester,
                        department=department,
                    )

            # Handle CourseGroups separately
            for group in course_groups:
                existing_group = CourseGroup.objects.filter(group_name=group).first()
                group_rows = df[df["GROUP"] == group]
                if group_rows.empty:
                    continue  # Skip if no matching group row
                course_code = group_rows["COURSECODE"].values[0]
                course = Course.objects.filter(code=course_code).first()
                if not existing_group:
                    if course:
                        CourseGroup.objects.create(
                            group_name=group,
                            course=course,
                        )
                else:
                    if course:
                        existing_group.course = course
                        existing_group.save()

            enrollments = Enrollment.objects.all()
            for index, row in df.iterrows():
                if pd.isna(row["STUDNUM"]):
                    continue   
                student_reg_no = str(int(row["STUDNUM"]))
                course_code = row["COURSECODE"]
                group_name = row["GROUP"]
                term = row["TERM"]

                student = Student.objects.filter(reg_no=student_reg_no).first()
                course = Course.objects.filter(code=course_code).first()
                group = CourseGroup.objects.filter(group_name=group_name).first()

                if student and course and group:
                 
                    existing_enrollment = enrollments.filter(
                        student=student, course=course
                    ).first()
                    if not existing_enrollment:
                        Enrollment.objects.create(
                            student=student,
                            course=course,
                            group=group,
                        )
                    else:
                        
                        if existing_enrollment.group != group:
                            existing_enrollment.group = group
                            existing_enrollment.save()

          
           

            return Response({"status": "Student Data Imported Successfully"})