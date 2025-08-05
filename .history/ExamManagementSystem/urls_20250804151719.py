 
from django.contrib import admin
from django.urls import path
from django.urls import path, include
from django.conf import settings
 

urlpatterns = [
    path("admin/", admin.site.urls),
    path('api/users/', include('users.urls')),
     path('api/courses/', include('courses.urls')),
     path('api/departments/', include('departments.urls')),
     path('api/schedules/', include('schedules.urls')),
     path('api/semesters/', include('semesters.urls')),
     path('api/rooms/', include('rooms.urls')),
     path('api/student/', include('student.urls')),
     path('api/exams/', include('exams.urls')),
      path('api/enrollments/', include('enrollments.urls')),
       path('api/notifications/', include('notifications.urls')),


     
]
