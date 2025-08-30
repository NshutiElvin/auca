from pprint import pprint
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from datetime import time
from schedules.models import MasterTimetable, MasterTimetableExam
from student.serializers import StudentSerializer
from .models import Student, Exam, StudentExam
from .serializers import ExamSerializer, StudentExamSerializer
from schedules.utils import (
    allocate_shared_rooms_updated,
    generate_exam_schedule,
    get_slot_name,
    verify_groups_compatiblity,
    which_suitable_slot_to_schedule_course_group,
    schedule_unscheduled_group
)
from django.db import transaction
from enrollments.models import Enrollment
from student.models import Student
from courses.serializers import CourseSerializer
from sharedapp.shared_serializer import CourseGroupSerializer
from courses.models import Course, CourseGroup
from django.db import transaction
from exams.models import UnscheduledExam
from sharedapp.models import UnscheduledExamGroup
from sharedapp.serializers import UnscheduledExamGroupSerializer
from sharedapp.shared_exams_serializers import UnscheduledExamSerializer
from django.utils.dateparse import parse_date
from django.conf import settings
import json
from .utils import decrypt_message
from pytz import timezone as pytz_timezone
from django.utils import timezone
from datetime import timedelta


class ExamViewSet(viewsets.ModelViewSet):
    queryset = (
        Exam.objects.select_related("group", "room")
        .all()
        .order_by("date", "start_time")
    )
    serializer_class = ExamSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        timetable_id = request.GET.get('id') 
        location= request.GET.get("location")
        print(location)
          
        queryset = self.filter_queryset(self.get_queryset())
        
        

        if timetable_id:
            try:
                queryset = queryset.filter(
                    mastertimetableexam__master_timetable_id=timetable_id
                )  
                if location:
                    queryset = queryset.filter(
                    mastertimetableexam__master_timetable_id=timetable_id,  mastertimetableexam__master_location_id=location, 
                ) 


                if not queryset.exists():
                    return Response({
                        "success": True,
                        "data": [],
                        "message": f"No exams found for MasterTimetable ID {timetable_id}",
                    })
                serializer = self.get_serializer(queryset, many=True)
                return Response({
                    "success": True,
                    "data": serializer.data,
                    "masterTimetable":timetable_id,
                    "message": "Exams fetched successfully",
                })

                    

            except ValueError:
                return Response({
                    "success": False,
                    "message": "Invalid MasterTimetable ID (must be an integer)",
                }, status=400)
        else:
        
            if location:
                    print("location found", location, sep=" ")
                    recent_timetable=MasterTimetable.objects.filter(location_id=location).order_by("-created_at").first()
                    print(recent_timetable.id)
                    queryset = queryset.filter(
                    mastertimetableexam__master_timetable_id=recent_timetable.id
                )     
                    
 
                    serializer = self.get_serializer(queryset, many=True)
                    return Response({
                        "success": True,
                        "data": serializer.data,
                        "masterTimetable":recent_timetable.id,
                        "message": "Exams fetched successfully",
                    })
            else:
                recent_timetable= MasterTimetable.objects.order_by("-created_at").first()
                queryset = queryset.filter(
                            mastertimetableexam__master_timetable_id=recent_timetable.id
                        ).distinct()  
                serializer = self.get_serializer(queryset, many=True)
                return Response({
                    "success": True,
                    "data": serializer.data,
                    "masterTimetable":recent_timetable.id,
                    "message": "Exams fetched successfully",
                })

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Fetched successfully",
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Created successfully",
            },
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)

        return Response(
            {"success": True, "message": "Deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )

    @action(detail=False, methods=["PUT"], url_path="publish")
    def publish_timetable(self, request):
        try:
            masterTimetable = request.data.get("masterTimetable")
            masterTimetable = MasterTimetable.objects.get(id=masterTimetable)
            if masterTimetable.status == "PUBLISHED":
                masterTimetable.status = "DRAFT"
            else:
                masterTimetable.status = "PUBLISHED"

            masterTimetable.save()
            return Response(
                {
                    "success": True,
                    "message": f"Exam timetable published successfully.",
                    "status": masterTimetable.status,
                }
            )

        except Exception as e:
            print(e)
            return Response(
                {
                    "success": False,
                    "message": f"Error updating the timetable status: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
 

    # @action(detail=False, methods=["post"], url_path="generate-exam-schedule")
    # def generate_exam_schedule_view(self, request):
    #     start_date_str = request.data.get("start_date")
    #     end_date_str = request.data.get("end_date")
    #     course_ids = request.data.get("course_ids")
    #     slots = request.data.get("slots")
    #     client_config = request.data.get("configurations", {})
    #     term = client_config.get("term")
    #     location = client_config.get("location")
    #     academic_year = client_config.get("academicYear")

    #     if start_date_str and "T" in start_date_str:
    #         start_date_str = start_date_str.split("T")[0]
    #     if end_date_str and "T" in end_date_str:
    #         end_date_str = end_date_str.split("T")[0]

    #     start_date = parse_date(start_date_str) if start_date_str else None
    #     end_date = parse_date(end_date_str) if end_date_str else None

    #     with transaction.atomic():
    #         master_timetable = MasterTimetable.objects.create(
    #             academic_year=academic_year,
    #             generated_by=request.user,
    #             start_date=start_date,
    #             end_date=end_date,
    #             location_id=int(location),
    #             semester_id=int(term),
    #         )

    #         exams, _, unscheduled, reasons = generate_exam_schedule(
    #             slots=slots,
    #             course_ids=course_ids,
    #             master_timetable=master_timetable,
    #             location=int(location),
    #         )

    #         queryset = self.filter_queryset(self.get_queryset())
    #         serializer = self.get_serializer(queryset, many=True)

    #         unscheduled_response = []
    #         unscheduled_course_ids = set()
    #         unscheduled_group_ids = set()
            
    #         # First, collect all course and group IDs from unscheduled items
    #         for course_group in unscheduled:
    #             for course_info in course_group.get("courses", []):
    #                 course_id = course_info.get("course_id")
    #                 groups = list(filter(None, course_info.get("groups", [])))
                    
    #                 if course_id and groups:  # Only consider if we have both course and groups
    #                     unscheduled_course_ids.add(course_id)
    #                     unscheduled_group_ids.update(groups)

    #         courses_map = {
    #             c.id: c for c in Course.objects.filter(id__in=unscheduled_course_ids)
    #         }
    #         groups_map = {
    #             g.id: g for g in CourseGroup.objects.filter(id__in=unscheduled_group_ids)
    #         }

    #         course_serializers_cache = {}
    #         group_serializers_cache = {}

    #         unscheduled_exam_objs = []
    #         unscheduled_exam_group_objs = []

    #         # Process unscheduled items to create exam entries
    #         for course_group in unscheduled:
    #             for course_info in course_group.get("courses", []):
    #                 course_id = course_info.get("course_id")
    #                 groups = list(filter(None, course_info.get("groups", [])))
                    
    #                 # Skip if no course ID or no groups
    #                 if not course_id or not groups:
    #                     continue
                    
    #                 # Skip if course not found in database
    #                 if course_id not in courses_map:
    #                     continue

    #                 course = courses_map[course_id]
    #                 # Use the first group's reason or default
    #                 reason = reasons.get(groups[0], "No reason provided")

    #                 # Check if any of the groups are already scheduled
    #                 unscheduled_groups_for_course = []
    #                 for group_id in groups:
    #                     group = groups_map.get(group_id)
    #                     if group  :
    #                         unscheduled_groups_for_course.append(group)
                    
    #                 # Only create unscheduled exam if there are actually unscheduled groups
    #                 if unscheduled_groups_for_course:
    #                     unscheduled_exam = UnscheduledExam(
    #                         course=course,
    #                         master_timetable=master_timetable,
    #                         reason=reason,
    #                     )
    #                     unscheduled_exam_objs.append(unscheduled_exam)
                        
    #                     # Prepare response data
    #                     c_data = {
    #                         "course": course_serializers_cache.setdefault(
    #                             course_id, CourseSerializer(course).data
    #                         ),
    #                         "groups": [],
    #                         "reason": reason,
    #                         "_unscheduled_exam_ref": unscheduled_exam,
    #                         "_groups": unscheduled_groups_for_course,
    #                     }
    #                     unscheduled_response.append(c_data)

    #         # Bulk create all unscheduled exams
    #         UnscheduledExam.objects.bulk_create(unscheduled_exam_objs)

    #         # Now create the exam-group relationships
    #         for c_data in unscheduled_response:
    #             unscheduled_exam = c_data.pop("_unscheduled_exam_ref")
    #             groups_for_exam = c_data.pop("_groups")
                
    #             for group in groups_for_exam:
    #                 unscheduled_exam_group_objs.append(
    #                     UnscheduledExamGroup(exam=unscheduled_exam, group=group)
    #                 )
    #                 c_data["groups"].append(
    #                     group_serializers_cache.setdefault(
    #                         group.id, CourseGroupSerializer(group).data
    #                     )
    #                 )

    #         # Bulk create all exam-group relationships
    #         UnscheduledExamGroup.objects.bulk_create(unscheduled_exam_group_objs)

    #         return Response(
    #             {
    #                 "success": True,
    #                 "message": f"{len(exams)} exams scheduled successfully.",
    #                 "data": serializer.data,
    #                 "unaccomodated": [],
    #                 "unscheduled": unscheduled_response,
    #             }
    #         )


    @action(detail=False, methods=["post"], url_path="generate-exam-schedule")
    def generate_exam_schedule_view(self, request):
        import datetime
        from django.db import transaction
        from collections import defaultdict

        with transaction.atomic():
            # Extract and parse request data
            start_date_str = request.data.get("start_date")
            end_date_str = request.data.get("end_date")
            course_ids = request.data.get("course_ids", None)
            slots = request.data.get("slots")
            client_config = request.data.get("configurations")
            term = client_config.get("term")
            location = client_config.get("location")
            academic_year = client_config.get("academicYear")

            # Parse dates more efficiently
            if start_date_str and "T" in start_date_str:
                start_date_str = start_date_str.split("T")[0]
            if end_date_str and "T" in end_date_str:
                end_date_str = end_date_str.split("T")[0]

            start_date = parse_date(start_date_str) if start_date_str else None
            end_date = parse_date(end_date_str) if end_date_str else None

            # Create master timetable
            master_timetable = MasterTimetable.objects.create(
                academic_year=academic_year,
                generated_by=request.user,
                start_date=start_date,
                end_date=end_date,
                location_id=int(location),
                semester_id=int(term)
            )

            # Generate exam schedule
            exams, _, unscheduled, reasons = generate_exam_schedule(
                slots=slots, 
                course_ids=course_ids, 
                master_timetable=master_timetable, 
                location=int(location), 
                
            )

            # Prepare response data
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)

            # Process unscheduled exams efficiently
            unScheduled = []
            unscheduled_courses = [course["courses"] for course in unscheduled]
            
            if unscheduled_courses:
                # Flatten and collect all unique course IDs and group IDs
                all_course_ids = set()
                all_group_ids = set()
                course_group_mapping = defaultdict(list)
                
                for unscheduleds_ in unscheduled_courses:
                    for unscheduled_ in unscheduleds_:
                        course_id = unscheduled_["course_id"]
                        groups = unscheduled_["groups"]
                        all_course_ids.add(course_id)
                        course_group_mapping[course_id].extend(groups)
                        all_group_ids.update(filter(None, groups))

                # Bulk fetch courses and enrollments
                courses_dict = {
                    course.id: course 
                    for course in Course.objects.filter(id__in=all_course_ids)
                }
                
                # Bulk fetch enrollments with related groups
                enrollments_dict = {}
                if all_group_ids:
                    enrollments = Enrollment.objects.filter(
                        course_id__in=all_course_ids,
                        group_id__in=all_group_ids
                    ).select_related('group', 'course')
                    
                    for enrollment in enrollments:
                        key = (enrollment.course_id, enrollment.group_id)
                        enrollments_dict[key] = enrollment

                # Process unscheduled exams in batches
                unscheduled_exams_to_create = []
                unscheduled_groups_to_create = []
                
                for unscheduleds_ in unscheduled_courses:
                    for unscheduled_ in unscheduleds_:
                        course_id = unscheduled_["course_id"]
                        groups = unscheduled_["groups"]
                        
                        course = courses_dict.get(course_id)
                        if not course:
                            continue
                        
                        # Filter out None/empty groups
                        valid_groups = [g for g in groups if g]
                        if not valid_groups:
                            continue
                        
                        # Get reason for first valid group
                        reason = reasons.get(valid_groups[0], "Unknown reason")
                        
                        # Prepare course data structure
                        c = {
                            "course": CourseSerializer(course).data,
                            "groups": [],
                            "reason": reason
                        }
                        
                        # Create unscheduled exam object (will be bulk created later)
                        unscheduled_exam_data = {
                            'course': course,
                            'master_timetable': master_timetable,
                            'reason': reason,
                            'groups_data': []
                        }
                        
                        # Process groups for this course
                        for group_id in valid_groups:
                            enrollment = enrollments_dict.get((course_id, group_id))
                            if enrollment:
                                c["groups"].append(CourseGroupSerializer(enrollment.group).data)
                                unscheduled_exam_data['groups_data'].append(enrollment.group)
                        
                        if c["groups"]:  # Only add if we have valid groups
                            unScheduled.append(c)
                            unscheduled_exams_to_create.append(unscheduled_exam_data)
                
                # Bulk create unscheduled exams
                if unscheduled_exams_to_create:
                    unscheduled_exam_objects = []
                    for exam_data in unscheduled_exams_to_create:
                        unscheduled_exam = UnscheduledExam.objects.create(
                            course=exam_data['course'],
                            master_timetable=exam_data['master_timetable'],
                            reason=exam_data['reason']
                        )
                        unscheduled_exam_objects.append(unscheduled_exam)
                        
                        # Bulk create groups for this exam
                        groups_to_create = [
                            UnscheduledExamGroup(exam=unscheduled_exam, group=group)
                            for group in exam_data['groups_data']
                        ]
                        
                        if groups_to_create:
                            UnscheduledExamGroup.objects.bulk_create(groups_to_create)
                            
                            # Add groups to the exam (using add with the created objects)
                            unscheduled_exam.groups.add(*[ug.id for ug in 
                                UnscheduledExamGroup.objects.filter(exam=unscheduled_exam)])

            return Response({
                "success": True,
                "message": f"{len(exams)} exams scheduled successfully.",
                "data": serializer.data,
                "unaccomodated": [],
                "unscheduled": unScheduled,
            })

    # @action(detail=False, methods=["post"], url_path="generate-exam-schedule")
    # def generate_exam_schedule_view(self, request):
    #     import datetime

    #     with transaction.atomic():

    #         start_date_str = request.data.get("start_date")
    #         end_date_str = request.data.get("end_date")
    #         course_ids = request.data.get("course_ids", None)
    #         slots = request.data.get("slots")
    #         client_config= request.data.get("configurations")
    #         term= client_config.get("term")
    #         location= client_config.get("location")
    #         academic_year=client_config.get("academicYear")
 
    #         if start_date_str and "T" in start_date_str:
    #             start_date_str = start_date_str.split("T")[0]
    #         if end_date_str and "T" in end_date_str:
    #             end_date_str = end_date_str.split("T")[0]

    #         start_date = parse_date(start_date_str) if start_date_str else None
    #         end_date = parse_date(end_date_str) if end_date_str else None
  
        
    #         master_timetable = MasterTimetable.objects.create(
    #             academic_year=academic_year,
    #             generated_by=request.user,
    #             start_date=start_date,
    #             end_date=end_date,
    #             location_id= int(location),
    #             semester_id=int(term)

    #         )
        

    #         exams, _, unscheduled, reasons = generate_exam_schedule(
    #             slots=slots, course_ids=course_ids, master_timetable=master_timetable, location=int(location), user_id=request.user.id
    #         )
    #         queryset = self.filter_queryset(self.get_queryset())
    #         serializer = self.get_serializer(queryset, many=True)
    #         # get real unscheduled exams in database
    #         unScheduled = []
    #         unscheduled_courses = [course["courses"] for course in unscheduled]
    #         if len(unscheduled_courses) > 0:
    #             with transaction.atomic():
    #                 for unscheduleds_ in unscheduled_courses:
    #                     for unscheduled_ in unscheduleds_:
    #                         unscheduled_course = unscheduled_["course_id"]
    #                         group = unscheduled_["groups"]
    #                         c = {}
    #                         course = Course.objects.get(id=unscheduled_course)
    #                         courseSerializer = CourseSerializer(course)
    #                         c["course"] = courseSerializer.data
    #                         c["groups"] = []
    #                         if any(group):
    #                             reason=reasons[group[0]]
    #                             c["reason"]=reason
    #                             unscheduled = UnscheduledExam.objects.create(
    #                                 course=course, master_timetable=master_timetable, reason=reason
    #                             )
    #                             for g in group:
    #                                 if not g:
    #                                     continue
    #                                 enrollement = Enrollment.objects.filter(
    #                                     course=course, group_id=g
    #                                 ).first()
                                
    #                                 unscheduled_group = UnscheduledExamGroup.objects.create(
    #                                     exam=unscheduled, group=enrollement.group
    #                                 )
    #                                 unscheduled.groups.add(unscheduled_group)
    #                                 courseGroupSerializer = CourseGroupSerializer(
    #                                     enrollement.group
    #                                 )
    #                                 c["groups"].append(courseGroupSerializer.data)
    #                             unScheduled.append(c)
    #                             unscheduled.save()

    #         return Response(
    #             {
    #                 "success": True,
    #                 "message": f"{len(exams)} exams scheduled successfully.",
    #                 "data": serializer.data,
    #                 "unaccomodated": [],
    #                 "unscheduled": unScheduled,
    #             }
    #         )

    @action(detail=False, methods=["GET"], url_path="unscheduled_exams")
    def unscheduled_exams(self, request):
        try:
            location=request.GET.get("location")

            exams = UnscheduledExam.objects.all()
            if location:
                recent_timetable=MasterTimetable.objects.filter(location_id=location).order_by("-created_at").first()
                exams = UnscheduledExam.objects.filter(master_timetable_id=recent_timetable.id)

            serializer = UnscheduledExamSerializer(exams, many=True)
         

            converted = map(
                lambda exam: {
                    **exam,
                    "groups": [
                        UnscheduledExamGroupSerializer(
                            UnscheduledExamGroup.objects.get(id=converted_group)
                        ).data
                        for converted_group in exam["group_id"]
                    ],
                    "group_id": None,
                },
                serializer.data,
            )

            return Response(
                {
                    "success": True,
                    "message": f"unscheduled exams retrieved successfully.",
                    "data": list(converted),
                }
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"Error getting unaccomodated exams: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="cancel-exam")
    def cancel_exam_view(self, request):
        try:
            exam_id = request.data.get("exam_id")
            if not exam_id:
                return Response(
                    {"success": False, "message": "Missing exam_id"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # cancel_exam(exam_id)
            return Response(
                {"success": True, "message": f"Exam {exam_id} cancelled successfully"}
            )
        except Exception as e:
            return Response(
                {"success": False, "message": f"Error cancelling exam: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"], url_path="reschedule-exam")
    def reschedule_exam_view(self, request):
        try:
            exam_id = request.data.get("exam_id")
            new_date_str = request.data.get("new_date")
            slot = request.data.get("slot", None)

            if not (exam_id and new_date_str):
                return Response(
                    {
                        "success": False,
                        "message": "Missing required fields: exam_id, new_date",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response(
                {
                    "success": True,
                    "message": f"Exam {exam_id} rescheduled successfully",
                    "data": serializer.data,
                }
            )
        except Exception as e:
            return Response(
                {"success": False, "message": f"Error rescheduling exam: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(
        detail=False,
        methods=["delete"],
        url_path="truncate-all",
        permission_classes=[permissions.IsAuthenticated],
    )
    def truncate_all(self, request):
        try:
            with transaction.atomic():
                StudentExam.objects.all().delete()
                # Exam.objects.all().delete()
                UnscheduledExam.objects.all().delete()
                UnscheduledExamGroup.objects.all().delete()

            return Response(
                {
                    "success": True,
                    "message": "All exams and student exam assignments have been truncated successfully.",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    @action(
        detail=False,
        methods=["delete"],
        url_path="truncate-mastertimetable",
        permission_classes=[permissions.IsAuthenticated],
    )
    def truncate_all(self, request):
        try:
            with transaction.atomic():
                master_timetableid=request.data.get("id")
                master_timetable= MasterTimetable.objects.get(id=master_timetableid)
                related_exams= master_timetable.exams.all() 
                StudentExam.objects.filter(exam__in=related_exams).delete()
                Exam.objects.filter(id__in=related_exams).delete()
                UnscheduledExam.objects.filter(master_timetable=master_timetable).delete()
                UnscheduledExamGroup.objects.filter(exam__master_timetable=master_timetable).delete()
                MasterTimetableExam.objects.filter(master_timetable=master_timetable).delete()
                master_timetable.delete()

            return Response(
                {
                    "success": True,
                    "message": "All exams and student exam assignments have been truncated successfully.",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )



    @action(
        detail=False,
        methods=["post"],
        url_path="add-exam-to-slot",
        permission_classes=[permissions.IsAuthenticated],
    )
    def add_new_exam(self, request):
        try:
            with transaction.atomic():
                existing_slot = request.data.get("slot")
                date = request.data.get("day")

                new_group_to_add = request.data.get("course_group")
                existing_groups = [
                    group["group"]["id"] for group in existing_slot["exams"]
                ]
                new_groups = []
                if new_group_to_add.get("groups") != None:
                    new_groups = [
                        group["group"]["id"] for group in new_group_to_add.get("groups")
                    ]
                else:
                    new_groups = [new_group_to_add.get("group").get("id")]

                merged_groups = [*existing_groups, *new_groups]
                date_formatted = parse_date(date)
                scheduled_date_groups = Exam.objects.filter(date=date_formatted)
                scheduled_date_groups = [
                    ex_group.group.id for ex_group in scheduled_date_groups
                ]
                merged_groups.extend(scheduled_date_groups)
                merged_groups = list(set(merged_groups))
                conflicts = verify_groups_compatiblity(merged_groups)
                conflict_matrix = []

                for conf in conflicts:

                    if conf[0] in new_groups:
                        g1 = CourseGroupSerializer(
                            CourseGroup.objects.get(id=conf[0])
                        ).data
                        g2 = CourseGroupSerializer(
                            CourseGroup.objects.get(id=conf[1])
                        ).data
                        g1_slot = Exam.objects.filter(group__id=conf[0]).first()
                        g2_slot = Exam.objects.filter(group__id=conf[1]).first()
                        if g1_slot:

                            g1["slot"] = g1_slot.slot_name
                        if g2_slot:
                            g2["slot"] = g2_slot.slot_name
                        conflicted_students= Student.objects.filter(id__in=conf[2])
                        serializer=StudentSerializer(conflicted_students, many=True)
                        conflict_matrix.append((g1, g2,  serializer.data))
                    if conf[1] in new_groups:
                        g1 = CourseGroupSerializer(
                            CourseGroup.objects.get(id=conf[1])
                        ).data
                        g2 = CourseGroupSerializer(
                            CourseGroup.objects.get(id=conf[0])
                        ).data
                        g1_slot = Exam.objects.filter(group__id=conf[0]).first()
                        g2_slot = Exam.objects.filter(group__id=conf[1]).first()
                        if g1_slot:

                            g1["slot"] = g1_slot.slot_name
                        if g2_slot:
                            g2["slot"] = g2_slot.slot_name
                        conflicted_students= Student.objects.filter(id__in=conf[2])
                        serializer=StudentSerializer(conflicted_students, many=True)
                        conflict_matrix.append((g1, g2,  serializer.data))
                new_group, best_suggestion, all_suggestions, all_conflicts = (
                    which_suitable_slot_to_schedule_course_group(
                        date_formatted, new_groups, existing_slot.get("name")
                    )
                )
                return Response(
                    {
                        "success": True,
                        "conflict": True,
                        "data": conflict_matrix,
                        "all_suggestions": all_suggestions,
                        "best_suggestion": best_suggestion,
                        "message": "Processcing finished with the following conflict.",
                    },
                    status=status.HTTP_200_OK,
                )
        except Exception as e:
            print(e)

            return Response(
                status=status.HTTP_200_OK,
            )


    @action(
        detail=False,
        methods=["patch"],
        url_path="changeTime",
        permission_classes=[permissions.IsAuthenticated],
    )
    def changeTime(self, request):

        try:
            with transaction.atomic():
                existing_slot = request.data.get("slotToChange")
                print(existing_slot)
                name = existing_slot.get("name")
                start_time = time.fromisoformat(existing_slot.get("start"))
                end_time = time.fromisoformat(existing_slot.get("end"))
                date = existing_slot.get("date")
                

                date = parse_date(date)
                print(name, start_time, end_time, date, sep="\n")
                exams= Exam.objects.filter(date=date, slot_name=name)
                for exam in exams:
                    exam.start_time = start_time
                    exam.end_time = end_time

                 
                Exam.objects.bulk_update(exams, fields=['start_time', 'end_time'])
                return Response(
                    {
                        "success": True,
                        "conflict": True,
                        
                        "message": "time changed successfully.",
                    },
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            print(e)
            return Response(
                {"success": False, "message": f"Error updating time: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="schedule-course-group",
        permission_classes=[permissions.IsAuthenticated],
    )
    def schedule_new_exam(self, request):

        try:
            with transaction.atomic():
                existing_slot = request.data.get("slot")
                date = request.data.get("day")
                new_group_to_add = request.data.get("course_group")
                date_formatted = parse_date(date)
                course_id = new_group_to_add["course"]["id"]
                course = Course.objects.get(id=course_id)
                weekday = date_formatted.strftime("%A")
                suggestedSlot = request.data.get("suggestedSlot")
                start_time = time.fromisoformat(existing_slot.get("start"))
                end_time = time.fromisoformat(existing_slot.get("end"))
                master_timetable = UnscheduledExam.objects.get(
                    id=new_group_to_add["id"]
                ).master_timetable
                if suggestedSlot:
                    existing_slot["name"] = suggestedSlot["slot"].lower()
                    date_formatted = parse_date(suggestedSlot["date"])
                if weekday == "Friday" and existing_slot["name"].lower() == "evening":
                    raise ValueError("We can't schedule exam on Friday evening.")
                for group in new_group_to_add["groups"]:

                    group_id = group["group"]["id"]
                    real_group = CourseGroup.objects.get(id=group_id, course=course)
                  
                    try:
                        exam = Exam.objects.create(
                            date=date_formatted,
                            start_time=start_time,
                            end_time=end_time,
                            group=real_group,
                        )
                        master_timetable.exams.add(exam)

                        student_ids = Enrollment.objects.filter(
                            course=course, group=real_group
                        ).values_list("student_id", flat=True)
                        for student_id in student_ids:
                            student_exam = StudentExam.objects.create(
                                student_id=student_id, exam=exam
                            )
                            student_exam.save()
                        # assigning rooms
                        existing_student_exams = (
                            StudentExam.objects.filter(
                                exam__date=date_formatted,
                                exam__start_time=start_time,
                                exam__end_time=end_time,
                            )
                            .select_related(
                                "exam", "exam__group__course__semester", "student"
                            )
                            .order_by("exam__date", "exam__start_time")
                        )
                        student_exams = (
                            StudentExam.objects.filter(
                                student_id__in=student_ids, exam=exam
                            )
                            .select_related(
                                "exam", "exam__group__course__semester", "student"
                            )
                            .order_by("exam__date", "exam__start_time")
                        )
                        student_exams = student_exams.union(existing_student_exams)
                        allocate_shared_rooms_updated(student_exams)

                    except Exception as e:
                        raise Exception(str(e))
                exam_to_delete = UnscheduledExam.objects.get(id=new_group_to_add["id"])
                exam_group = UnscheduledExamGroup.objects.filter(exam=exam_to_delete)
                exam_group.delete()
                exam_to_delete.delete()

            return Response(
                {
                    "success": True,
                    "conflict": True,
                    "message": "Exam Scheduled Successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            print(str(e))
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="schedule-course-single-group",
        permission_classes=[permissions.IsAuthenticated],
    )
    def schedule_course_single_group(self, request):
        from datetime import time

        try:
            with transaction.atomic():
                existing_slot = request.data.get("slot")
                date = request.data.get("day")
                new_group_to_add = request.data.get("course_group")
                date_formatted = parse_date(date)
                start_time = time.fromisoformat(existing_slot.get("start"))
                end_time = time.fromisoformat(existing_slot.get("end"))
                weekday = date_formatted.strftime("%A")
                exam = new_group_to_add.get("exam")
                group = new_group_to_add.get("group")
                course_id = exam["course"]["id"]
                course = Course.objects.get(id=course_id)

                if weekday == "Friday" and existing_slot.name.lower() == "evening":
                    raise ValueError("We can't schedule exam on Friday evening.")
                group_id = group.get("id")
                real_exam = UnscheduledExam.objects.get(id=exam.get("id"))
                master_timetable = real_exam.master_timetable
                real_group = CourseGroup.objects.get(id=group_id)
                real_group = UnscheduledExamGroup.objects.get(
                    group=real_group, exam=real_exam
                )

                try:
                    exam = Exam.objects.create(
                        date=date_formatted,
                        start_time=start_time,
                        end_time=end_time,
                        group=real_group.group,
                    )
                    master_timetable.exams.add(exam)

                    # Update student exam dates
                    student_ids = Enrollment.objects.filter(
                        course=course, group=real_group.group
                    ).values_list("student_id", flat=True)
                    for student_id in student_ids:
                        student_exam = StudentExam.objects.create(
                            student_id=student_id, exam=exam
                        )
                        student_exam.save()
                    existing_student_exams = (
                        StudentExam.objects.filter(
                            exam__date=date_formatted,
                            exam__start_time=start_time,
                            exam__end_time=end_time,
                        )
                        .select_related(
                            "exam", "exam__group__course__semester", "student"
                        )
                        .order_by("exam__date", "exam__start_time")
                    )
                    student_exams = (
                        StudentExam.objects.filter(
                            student_id__in=student_ids, exam=exam
                        )
                        .select_related(
                            "exam", "exam__group__course__semester", "student"
                        )
                        .order_by("exam__date", "exam__start_time")
                    )
                    student_exams = student_exams.union(existing_student_exams)
                    allocate_shared_rooms_updated(student_exams)
                except UnscheduledExam .DoesNotExist:
                    pass

                except Exception as e:
                    raise Exception(str(e))

                real_exam.groups.remove(real_group.id)
                if real_exam.groups.count() == 0:
                    real_exam.delete()

            return Response(
                {
                    "success": True,
                    "conflict": True,
                    "message": "Exam Scheduled Successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            print(str(e))
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="schedule-existing-course-single-group",
        permission_classes=[permissions.IsAuthenticated],
    )
    def schedule_existing_course_single_group(self, request):

        try:
            with transaction.atomic():
                existing_slot = request.data.get("slot")
                print(request.data.get("slot"))
                date = request.data.get("day")
                new_group_to_add = request.data.get("course_group")
                date_formatted = parse_date(date)
                weekday = date_formatted.strftime("%A")
                exam = new_group_to_add.get("exam")
                exam = Exam.objects.get(id=exam.get("id"))
                start_time = time.fromisoformat(existing_slot.get("start"))
                end_time = time.fromisoformat(existing_slot.get("end"))

                if weekday == "Friday" and existing_slot.name.lower() == "evening":
                    raise ValueError("We can't schedule exam on Friday evening.")

                try:
                    exam.start_time = start_time
                    exam.end_time = end_time
                    exam.date = date_formatted
                    exam.save()
                    student_ids = Enrollment.objects.filter(
                        course=exam.group.course, group=exam.group
                    ).values_list("student_id", flat=True)
                    existing_student_exams = (
                        StudentExam.objects.filter(
                            exam__date=date_formatted,
                            exam__start_time=start_time,
                            exam__end_time=end_time,
                        )
                        .select_related(
                            "exam", "exam__group__course__semester", "student"
                        )
                        .order_by("exam__date", "exam__start_time")
                    )
                    student_exams = (
                        StudentExam.objects.filter(
                            student_id__in=student_ids, exam=exam
                        )
                        .select_related(
                            "exam", "exam__group__course__semester", "student"
                        )
                        .order_by("exam__date", "exam__start_time")
                    )
                    student_exams = student_exams.union(existing_student_exams)
                    allocate_shared_rooms_updated(student_exams)

                except Exception as e:
                    raise Exception(str(e))

            return Response(
                {
                    "success": True,
                    "conflict": True,
                    "message": "Exam Scheduled Successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            print(str(e))
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["patch"],
        url_path="remove-scheduled-exam",
        permission_classes=[permissions.IsAuthenticated],
    )
    def remove_exam(self, request):
        try:
            with transaction.atomic():
                date = request.data.get("day")
                group_id = request.data.get("group_id")
                date_formatted = parse_date(date)
                exam = Exam.objects.filter(
                    group__id=group_id, date=date_formatted
                ).first()
                master_timetable = MasterTimetableExam.objects.get(
                    exam=exam
                ).master_timetable
                course = exam.group.course
                unscheduled = None
                try:
                    unscheduled = UnscheduledExam.objects.get(course=course)
                except UnscheduledExam.DoesNotExist:

                    unscheduled = UnscheduledExam.objects.create(
                        course=course, master_timetable=master_timetable
                    )
                unscheduled_group = UnscheduledExamGroup.objects.create(
                    exam=unscheduled, group=exam.group
                )
                unscheduled.groups.add(unscheduled_group)
                unscheduled.save()
                student_ids = Enrollment.objects.filter(
                    course=course, group=exam.group
                ).values_list("student_id", flat=True)

                StudentExam.objects.filter(
                    student_id__in=student_ids, exam=exam
                ).select_related(
                    "exam", "exam__group__course__semester", "student"
                ).order_by(
                    "exam__date", "exam__start_time"
                ).delete()
                existing_student_exams = (
                    StudentExam.objects.filter(
                        exam__date=date_formatted,
                        exam__start_time=exam.start_time,
                        exam__end_time=exam.end_time,
                    )
                    .select_related("exam", "exam__group__course__semester", "student")
                    .order_by("exam__date", "exam__start_time")
                )

                allocate_shared_rooms_updated(existing_student_exams)
                master_timetable.exams.remove(exam)
                exam.delete()
                exams = UnscheduledExam.objects.all()
                serializer = UnscheduledExamSerializer(exams, many=True)

                converted = map(
                    lambda exam: {
                        **exam,
                        "groups": [
                            UnscheduledExamGroupSerializer(
                                UnscheduledExamGroup.objects.get(id=converted_group)
                            ).data
                            for converted_group in exam["group_id"]
                        ],
                        "group_id": None,
                    },
                    serializer.data,
                )

                return Response(
                    {
                        "success": True,
                        "message": f"Exam removed successfully",
                        "unscheduled": list(converted),
                        # "scheduled":scheduled
                    }
                )

        except Exception as e:

            print(e)
            return Response(
                {"success": False, "message": f"Error truncating data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StudentExamViewSet(viewsets.ModelViewSet):
    queryset = StudentExam.objects.select_related("student", "exam", "room").all()
    serializer_class = StudentExamSerializer

    # permission_classes=[permissions.IsAuthenticated]
    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAuthenticated]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(
                {
                    "success": True,
                    "data": serializer.data,
                    "message": "Fetched successfully",
                }
            )

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Fetched successfully",
            }
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Fetched successfully",
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Created successfully",
            },
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"success": True, "message": "Deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request, *args, **kwargs):
        try:
            student = request.user.student

        except Student.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Student profile not found for this user.",
                },
                status=404,
            )

        exams = StudentExam.objects.filter(student=student)
        masterTimetable = MasterTimetableExam.objects.get(exam=exams[0].exam)
        serializer = StudentExamSerializer(exams, many=True)
        return Response(
            {
                "success": True,
                "data": (
                    serializer.data
                    if masterTimetable.master_timetable.status == "PUBLISHED"
                    else []
                ),
                "message": "Fetched successfully",
            }
        )

    @action(detail=False, methods=["get"], url_path="time")
    def get_exam_qcode_expiration_time(self, request, *args, **kwargs):
        try:

            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            expiration_time = now + timedelta(minutes=settings.QRCODE_LIFETIME)

            return Response(
                {"success": True, "time": expiration_time},
                status=200,
            )

        except Exception as e:
            print(e)
            return Response(
                {
                    "success": False,
                    "message": f"An error occurred: {str(e)}",
                },
                status=500,
            )

    @action(detail=False, methods=["post"], url_path="verify")
    def verify(self, request, *args, **kwargs):
        try:

            data = request.data

            encryptedData = data.get("encryptedData")

            try:
                decrypted_data = decrypt_message(encryptedData, settings.ENCRYPTION_KEY)
                data = json.loads(decrypted_data)
                tz = pytz_timezone(settings.TIME_ZONE)
                now = timezone.now().astimezone(tz)
                qr_expiration_time_str = data.get("expirationTime")
                expiration_time = timezone.datetime.fromisoformat(
                    qr_expiration_time_str
                )
                is_expired = now > expiration_time
                if is_expired:
                    return Response(
                        {
                            "success": False,
                            "message": "QR Code expired",
                        },
                        status=400,
                    )

            except:
                return Response(
                    {
                        "success": False,
                        "message": f"Invalid QR code",
                    },
                    status=500,
                )
            student_id = data.get("studentId")
            student = Student.objects.get(user_id=student_id)
            enrollments = Enrollment.objects.filter(student_id=student.id)

            if not enrollments.exists():
                return Response(
                    {
                        "success": False,
                        "message": "No enrolled courses found for this student.",
                    },
                    status=404,
                )

            # Calculate totals across all enrollments
            total_to_pay = sum(enrollment.amount_to_pay for enrollment in enrollments)
            total_paid = sum(enrollment.amount_paid for enrollment in enrollments)
            all_paid = total_to_pay == total_paid

            # Get first enrollment for the response format (maintaining your original structure)
            first_enrollment = enrollments.first()
            course_serializer = CourseSerializer(first_enrollment.course)

            if all_paid:
                return Response(
                    {
                        "success": True,
                        "data": {
                            "status": True,
                            "message": "You have paid your full payment",
                            "course": course_serializer.data,
                            "studentName": f"{student.user.first_name} {student.user.last_name}",
                            "studentRegNumber": student.reg_no,
                            "amountToPay": total_to_pay,
                            "amountPaid": total_paid,
                        },
                    },
                    status=200,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "data": {
                            "status": False,
                            "message": "You haven't paid for all courses",
                            "course": course_serializer.data,
                            "studentName": f"{student.user.first_name} {student.user.last_name}",
                            "studentRegNumber": student.reg_no,
                            "amountToPay": total_to_pay,
                            "amountPaid": total_paid,
                        },
                    },
                    status=200,
                )

        except Student.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Student profile not found for this user.",
                },
                status=404,
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"An error occurred: {str(e)}",
                },
                status=500,
            )


import random
