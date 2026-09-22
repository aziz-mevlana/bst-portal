from django.urls import path

from . import views


app_name = 'capstone'

urlpatterns = [
    path('', views.student_home, name='student_home'),
    path('start/', views.student_start, name='student_start'),
    path(
        'tasks/<int:task_id>/submit/',
        views.student_task_submit,
        name='student_task_submit',
    ),
    path('advisor/', views.advisor_home, name='advisor_home'),
    path(
        'advisor/projects/<int:project_id>/',
        views.advisor_project_detail,
        name='advisor_project_detail',
    ),
    path(
        'advisor/checkpoints/<int:checkpoint_id>/tasks/create/',
        views.advisor_task_create,
        name='advisor_task_create',
    ),
    path(
        'advisor/submissions/<int:attempt_id>/review/',
        views.advisor_submission_review,
        name='advisor_submission_review',
    ),
    path(
        'submission-files/<int:file_id>/download/',
        views.submission_file_download,
        name='submission_file_download',
    ),
]
