from django.urls import path

from . import views


app_name = 'capstone'

urlpatterns = [
    path('', views.student_home, name='student_home'),
    path('start/', views.student_start, name='student_start'),
    path('proposals/<int:proposal_id>/withdraw/', views.student_proposal_withdraw, name='student_proposal_withdraw'),
    path(
        'tasks/<int:task_id>/submit/',
        views.student_task_submit,
        name='student_task_submit',
    ),
    path('advisor/', views.advisor_home, name='advisor_home'),
    path('advisor/proposals/<int:proposal_id>/decide/', views.advisor_proposal_decide, name='advisor_proposal_decide'),
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
    path('advisor/checkpoints/<int:checkpoint_id>/evaluate/', views.advisor_checkpoint_evaluate, name='advisor_checkpoint_evaluate'),
    path('advisor/projects/<int:project_id>/complete/', views.advisor_project_complete, name='advisor_project_complete'),
    path(
        'submission-files/<int:file_id>/download/',
        views.submission_file_download,
        name='submission_file_download',
    ),
]
