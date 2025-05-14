from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
     
    ExamViewSet, StudentExamViewSet
  
)

router = DefaultRouter()
router.register(r'', ExamViewSet)
router.register(r'student-exam', StudentExamViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
