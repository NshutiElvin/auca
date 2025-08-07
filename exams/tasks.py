from celery import shared_task
from django.utils import timezone


from schedules.models import MasterTimetableExam
from student.models import Student
from .models import Exam, StudentExam
from datetime import datetime
from pytz import timezone as pytz_timezone
from django.conf import settings
from notifications.models import Notification
from notifications.tasks import send_notification, send_email_task

from celery import group
 

def _notify_students(exam, message):
    students = StudentExam.objects.filter(exam=exam).select_related('student__user')
    print(f"[NOTIFY] Sending notifications to {students.count()} students for '{exam.group.course.title}'.")
    
    notifications = []
    for student_exam in students:
        notifications.append(
            Notification(
                user=student_exam.student.user,
                title="Exam Update",
                message=f"{message}, Room: {student_exam.room.name}"
            )
        )
    
    created_notifications = Notification.objects.bulk_create(notifications)
    
    notification_tasks = []
    email_tasks = []
    
    for notification, student_exam in zip(created_notifications, students):
        notification_message = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at.isoformat(),
            "is_read": notification.is_read,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
        }
        notification_tasks.append(send_notification.s(notification_message, student_exam.student.user.id))
        email_tasks.append(send_email_task.s(
            subject=notification.title,
            message=notification.message,
            from_email=None,
            recipient_list=[student_exam.student.user.email],
        ))
    
    job = group(notification_tasks + email_tasks)
    job.apply_async()

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
            start_dt = datetime.combine(exam.date, exam.start_time)
            end_dt = datetime.combine(exam.date, exam.end_time)

            start_time = timezone.make_aware(start_dt) if timezone.is_naive(start_dt) else start_dt
            end_time = timezone.make_aware(end_dt) if timezone.is_naive(end_dt) else end_dt

            time_diff = (start_time - now).total_seconds()

            print(f"[INFO] Exam: {exam.group.course.title}, Status: {exam.status}, "
                f"Now: {now}, Start: {start_time}, End: {end_time}, Diff: {time_diff}s")
 
            if 0 < time_diff <= 900 and exam.status != 'READY':
                exam.status = 'READY'
                exam.save(update_fields=['status'])
                _notify_students(exam,
                    f"Your exam '{exam.group.course.title}' is starting soon "
                    f"({exam.date} {exam.start_time}-{exam.end_time}).")
                print(f"[UPDATE] Exam '{exam}' set to READY.")

            elif start_time <= now < end_time and exam.status != 'ONGOING':
                exam.status = 'ONGOING'
                exam.save(update_fields=['status'])
                print(f"[UPDATE] Exam '{exam}' set to ONGOING.")

            elif now >= end_time and exam.status != 'COMPLETED':
                exam.status = 'COMPLETED'
                exam.save(update_fields=['status'])
                _notify_students(exam,
                    f"Your exam '{exam.group.course.title}' scheduled on "
                    f"{exam.date} {exam.start_time}-{exam.end_time} has been marked as completed.")
                print(f"[UPDATE] Exam '{exam}' set to COMPLETED.")

            else:
                print(f"[NO CHANGE] Exam '{exam}' remains {exam.status}.")

