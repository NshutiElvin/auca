from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from .models import Exam, StudentExam
from django.utils.timezone import make_aware
from datetime import datetime


@shared_task
def check_and_update_exams():
    print("Making checking")
    now = timezone.now()
    today = now.date()

    exams_today = Exam.objects.filter(date=today)

    for exam in exams_today:
        start_dt = datetime.combine(exam.date, exam.start_time)
        end_dt = datetime.combine(exam.date, exam.end_time)

        start_time = timezone.make_aware(start_dt) if timezone.is_naive(start_dt) else start_dt
        end_time = timezone.make_aware(end_dt) if timezone.is_naive(end_dt) else end_dt

        print(f"Exam: {exam.group.course.title}, Now: {now}, Start: {start_time}, End: {end_time}, Current: {exam.status}")

        if 0 < (start_time - now).total_seconds() <= 900 and exam.status != 'READY':
            exam.status = 'READY'
            exam.save()
            _notify_students(exam, f"Your exam of {exam.group.course.title} scheduled at {exam.date} {exam.start_time}-{exam.end_time} will start soon.")

        elif start_time <= now < end_time and exam.status != 'ONGOING':
            exam.status = 'ONGOING'
            exam.save()

        elif now >= end_time and exam.status != 'COMPLETED':
            exam.status = 'COMPLETED'
            exam.save()
            _notify_students(exam, f"Your exam of {exam.group.course.title} scheduled on {exam.date} {exam.start_time}-{exam.end_time} has completed.")


def _notify_students(exam, message):
    students = StudentExam.objects.filter(exam=exam)
    for student in students:
        send_mail(
            subject="Exam Update",
            message=f"Hello {student.student.user.first_name},\n\n{message}",
            from_email=None,
            recipient_list=[student.student.user.email],
        )
