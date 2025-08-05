from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail

from schedules.models import MasterTimetable, MasterTimetableExam
from student.models import Student
from .models import Exam, StudentExam
from datetime import datetime
from pytz import timezone as pytz_timezone
from django.conf import settings
from notifications.models import Notification
from notifications.tasks import send_notification


@shared_task
def check_and_update_exams():
    tz = pytz_timezone(settings.TIME_ZONE )
    now = timezone.now().astimezone(tz) 
    today = now.date()

    exams_today = Exam.objects.filter(date=today)
    masterTimetable= MasterTimetableExam.objects.filter(exam=exams_today.first()).first().master_timetable

    print(f"[TASK] Checking {exams_today.count()} exams for {today}, current time: {now}")

    if masterTimetable.status=="PUBLISHED":
    

        for exam in exams_today:
            _notify_students(exam, "Helllllllllllllll")
            # Combine date and time safely
            start_dt = datetime.combine(exam.date, exam.start_time)
            end_dt = datetime.combine(exam.date, exam.end_time)

            start_time = timezone.make_aware(start_dt) if timezone.is_naive(start_dt) else start_dt
            end_time = timezone.make_aware(end_dt) if timezone.is_naive(end_dt) else end_dt

            time_diff = (start_time - now).total_seconds()

            print(f"[INFO] Exam: {exam.group.course.title}, Status: {exam.status}, "
                f"Now: {now}, Start: {start_time}, End: {end_time}, Diff: {time_diff}s")

            # ---- Status transitions ----
            # 1️⃣ READY: 15 min before start
            if 0 < time_diff <= 900 and exam.status != 'READY':
                exam.status = 'READY'
                exam.save(update_fields=['status'])
                _notify_students(exam,
                    f"Your exam '{exam.group.course.title}' is starting soon "
                    f"({exam.date} {exam.start_time}-{exam.end_time}).")
                print(f"[UPDATE] Exam '{exam}' set to READY.")

            # 2️⃣ ONGOING: Between start and end
            elif start_time <= now < end_time and exam.status != 'ONGOING':
                exam.status = 'ONGOING'
                exam.save(update_fields=['status'])
                print(f"[UPDATE] Exam '{exam}' set to ONGOING.")

            # 3️⃣ COMPLETED: After end time
            elif now >= end_time and exam.status != 'COMPLETED':
                exam.status = 'COMPLETED'
                exam.save(update_fields=['status'])
                _notify_students(exam,
                    f"Your exam '{exam.group.course.title}' scheduled on "
                    f"{exam.date} {exam.start_time}-{exam.end_time} has been marked as completed.")
                print(f"[UPDATE] Exam '{exam}' set to COMPLETED.")

            else:
                print(f"[NO CHANGE] Exam '{exam}' remains {exam.status}.")


def _notify_students(exam, message):
    students = StudentExam.objects.filter(exam=exam)
    print(f"[NOTIFY] Sending notifications to {students.count()} students for '{exam.group.course.title}'.")
    student= Student.objects.get(user__id=4)
    notification=Notification.objects.create(
    user=student.user,
    title="Exam Update",
    message=f"{message}, Room: "
)
    notification_message={
              "id": notification.id,
                "title":notification.title ,
                "message":notification.message ,
                "created_at":notification.created_at.isoformat(),
                "is_read":notification.is_read,
                "read_at": notification.read_at.isoformat(),
        }
    send_notification.delay(notification_message, student.user.id)
    # for student_exam in students:
    #     student = student_exam.student.user
    #     notification=Notification.objects.create(
    #         user=student,
    #         title="Exam Update",
    #         message=f"{message}, Room: {student_exam.room.name}"
    #     )
    #     notification_message={
    #           "id": notification.id,
    #             "title":notification.title ,
    #             "message":notification.message ,
    #             "created_at": notification.created_at,
    #             "is_read":notification.is_read,
    #             "read_at": notification.read_at,
    #     }
    #     send_notification.delay(notification_message, student.id)
    #     send_mail(
    #         subject="Exam Update",
    #         message=f"Hello {student.first_name},\n\n{message}, Room: {student_exam.room.name}",
    #         from_email=None,
    #         recipient_list=[student.email],
    #     )
