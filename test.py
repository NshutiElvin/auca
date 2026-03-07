from exams.models import Exam
from schedules.models import MasterTimetable

# Pick the Gishushu timetable (198)
t = MasterTimetable.objects.get(pk=198)

# Check ACCT 8112 exam
exam = Exam.objects.filter(
    master_timetable=t,
    group__course__code="ACCT 8112"
).first()

print(exam.id)
print(exam.master_timetable.location.name)

# How many StudentExams?
print(exam.studentexam_set.count())

# Are all those students' campuses the same?
from exams.models import StudentExam
ses = StudentExam.objects.filter(exam=exam).select_related("student")
campuses = set()
for se in ses:
    # what location/campus does this student belong to?
    print(se.student.__dict__)  # show all fields
    break  # just check one student's fields