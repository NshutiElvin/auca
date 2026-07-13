import resend
import os

resend.api_key = os.environ.get("RESEND_API_KEY")


def send_mail(subject, message, from_email, recipient_list, **kwargs):

    from_email = from_email or os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    resend.Emails.send({
        "from": from_email,
        "to": recipient_list,
        "subject": subject,
        "text": message,
    })


def notify_students_room_changed(changes):
    """
    In-app-only notification (DB row + WebSocket push, no email — per
    product decision) for students whose room was reassigned AFTER they
    were already seated. `changes` is an iterable of
    (student_exam, old_room, new_room) tuples.

    Deferred import of notifications.tasks to avoid a circular import
    (tasks.py imports send_mail from this module).
    """
    from notifications.models import Notification
    from notifications.tasks import send_notification
    from celery import group

    changes = [c for c in changes if c[1] and c[2] and c[1].id != c[2].id]
    if not changes:
        return

    notifications = []
    for student_exam, old_room, new_room in changes:
        course_title = student_exam.exam.group.course.title
        notifications.append(
            Notification(
                user=student_exam.student.user,
                title="Room Changed",
                message=(
                    f"Your room for '{course_title}' has changed from "
                    f"{old_room.name} to {new_room.name}."
                ),
            )
        )
    created = Notification.objects.bulk_create(notifications)

    tasks = []
    for notification in created:
        message = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at.isoformat(),
            "is_read": notification.is_read,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
        }
        tasks.append(send_notification.s(message, notification.user_id))

    group(tasks).apply_async()
