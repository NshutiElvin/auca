from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ExamManagementSystem.settings')  

app = Celery('ExamManagementSystem')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
app.conf.timezone = settings.TIME_ZONE


app.conf.beat_schedule = {
    'check-and-update-exams-every-minute': {
        'task': 'exams.tasks.check_and_update_exams',
        'schedule': 60.0,  
    },
}