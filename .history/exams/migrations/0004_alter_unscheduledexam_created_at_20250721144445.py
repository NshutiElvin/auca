# Generated by Django 5.2.1 on 2025-07-21 12:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0003_unscheduledexam_groups"),
    ]

    operations = [
        migrations.AlterField(
            model_name="unscheduledexam",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
