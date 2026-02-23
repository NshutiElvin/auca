from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.conf import settings
from datetime import datetime
from pytz import timezone as pytz_timezone

from schedules.models import MasterTimetableExam
from exams.models import Exam, StudentExam
from notifications.models import Notification
from notifications.tasks import send_notification, send_email_task


def _notify_students(exam, message):
    students = StudentExam.objects.filter(exam=exam).select_related('student__user')
    
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
    
    for notification, student_exam in zip(created_notifications, students):
        notification_message = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at.isoformat(),
            "is_read": notification.is_read,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
        }
        send_notification(notification_message, student_exam.student.user.id)
        send_email_task(
            subject=notification.title,
            message=notification.message,
            from_email=None,
            recipient_list=[student_exam.student.user.email],
        )


class CheckAndUpdateExamsWebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        tz = pytz_timezone(settings.TIME_ZONE)
        now = timezone.now().astimezone(tz)
        today = now.date()

        exams_today = Exam.objects.filter(date=today).prefetch_related(
            'mastertimetableexam_set__master_timetable'
        )

        if not exams_today.exists():
            return Response({'message': 'No exams today.'}, status=status.HTTP_200_OK)

        results = []
        skipped = []

        for exam in exams_today:
            # Find all published timetables for this exam
            published_entries = MasterTimetableExam.objects.filter(
                exam=exam,
                master_timetable__status="PUBLISHED"
            ).select_related('master_timetable')

            if not published_entries.exists():
                skipped.append({'exam': str(exam), 'reason': 'No published timetable found.'})
                continue

            start_dt = datetime.combine(exam.date, exam.start_time)
            end_dt = datetime.combine(exam.date, exam.end_time)

            start_time = timezone.make_aware(start_dt) if timezone.is_naive(start_dt) else start_dt
            end_time = timezone.make_aware(end_dt) if timezone.is_naive(end_dt) else end_dt

            time_diff = (start_time - now).total_seconds()
            previous_status = exam.status

            if 0 < time_diff <= 900 and exam.status != 'READY':
                exam.status = 'READY'
                exam.save(update_fields=['status'])

            elif start_time <= now < end_time and exam.status != 'ONGOING':
                exam.status = 'ONGOING'
                exam.save(update_fields=['status'])

            elif now >= end_time and exam.status != 'COMPLETED':
                exam.status = 'COMPLETED'
                exam.save(update_fields=['status'])

            results.append({
                'exam': str(exam),
                'course': exam.group.course.title,
                'previous_status': previous_status,
                'new_status': exam.status,
                'updated': previous_status != exam.status,
                'published_timetables': [entry.master_timetable.id for entry in published_entries],
            })

        return Response({
            'timestamp': now.isoformat(),
            'exams_processed': len(results),
            'exams_skipped': skipped,
            'results': results,
        }, status=status.HTTP_200_OK)