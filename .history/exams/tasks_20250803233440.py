from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from .models import Exam, StudentExam

@shared_task
def check_and_update_exams():
    print("Making checking")
    now = timezone.now()
    today = now.date()

    exams_today = Exam.objects.filter(date=today)

    for exam in exams_today:
        start_time = timezone.make_aware(
            timezone.datetime.combine(exam.date, exam.start_time)
        )

        end_time = timezone.make_aware(
            timezone.datetime.combine(exam.date, exam.end_time)
        )
        print(exam, end_time)
        # If exam is 15 min away and not marked ready
        if 0 < (start_time - now).total_seconds() <= 900 and exam.status != 'READY':
            exam.status = 'READY'
            exam.save()
            _notify_students(exam, "Your exam will start soon.")

        # If exam has already started and not marked completed
       
        elif now >= end_time:
            print(exam)
            exam.status = 'COMPLETED'
            exam.save()
            _notify_students(exam, "Your exam has been marked as completed.")


def _notify_students(exam, message):
    students = StudentExam.objects.filter(exam=exam)
    for student in students:
        send_mail(
            subject="Exam Update",
            message=f"Hello {student.student.user.first_name},\n\n{message}",
            from_email=None,
            recipient_list=[student.student.user.email],
        )
