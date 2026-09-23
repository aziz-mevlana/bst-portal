from django.urls import path

from . import views, academic_views


app_name = 'capstone'

urlpatterns = [
    path('', views.student_home, name='student_home'),
    path('start/', views.student_start, name='student_start'),
    path('advisor/students/', academic_views.student_pool, name='student_pool'),
    path('advisor/students/enroll/', academic_views.student_enroll, name='student_enroll'),
    path('advisor/students/<int:enrollment_id>/claim/', academic_views.advisor_claim, name='advisor_claim'),
    path('advisor/students/<int:enrollment_id>/unassign/', academic_views.advisor_unassign, name='advisor_unassign'),
    path('advisor/students/<int:enrollment_id>/change/', academic_views.advisor_change, name='advisor_change'),
    path('advisor/plan/', academic_views.plan_home, name='plan_home'),
    path('advisor/plans/<int:plan_id>/checkpoints/', academic_views.plan_checkpoint_save, name='plan_checkpoint_create'),
    path('advisor/plans/<int:plan_id>/checkpoints/<int:checkpoint_id>/', academic_views.plan_checkpoint_save, name='plan_checkpoint_edit'),
    path('advisor/plan-checkpoints/<int:checkpoint_id>/archive/', academic_views.plan_checkpoint_archive, name='plan_checkpoint_archive'),
    path('advisor/plan-checkpoints/<int:checkpoint_id>/expectations/', academic_views.expectation_add, name='expectation_add'),
    path('advisor/plans/<int:plan_id>/template/', academic_views.template_save, name='template_save'),
    path('advisor/plans/<int:plan_id>/template/<int:template_id>/apply/', academic_views.template_apply, name='template_apply'),
    path('advisor/progress/', academic_views.progress_matrix, name='progress_matrix'),
    path('advisor/projects/<int:project_id>/report/', academic_views.process_report, name='process_report'),
    path('projects/<int:project_id>/checkpoints/<int:checkpoint_id>/submit/', academic_views.checkpoint_submit, name='checkpoint_submit'),
    path('projects/<int:project_id>/checkpoints/<int:checkpoint_id>/items/<int:item_id>/toggle/', academic_views.checklist_toggle, name='checklist_toggle'),
    path('advisor/projects/<int:project_id>/checkpoints/<int:checkpoint_id>/extend/', academic_views.deadline_extend, name='deadline_extend'),
    path('advisor/academic-submissions/<int:submission_id>/review/', academic_views.checkpoint_review, name='checkpoint_review'),
    path('projects/<int:project_id>/literature/', academic_views.literature_upload, name='literature_upload'),
    path('advisor/literature/<int:version_id>/review/', academic_views.literature_review, name='literature_review'),
    path('projects/<int:project_id>/help/', academic_views.help_create, name='help_create'),
    path('help/<int:help_id>/reply/', academic_views.help_reply, name='help_reply'),
    path('help/<int:help_id>/resolve/', academic_views.help_resolve, name='help_resolve'),
    path('projects/<int:project_id>/meetings/', academic_views.meeting_create, name='meeting_create'),
    path('advisor/meetings/<int:meeting_id>/decide/', academic_views.meeting_decide, name='meeting_decide'),
    path('advisor/meetings/<int:meeting_id>/record/', academic_views.meeting_record, name='meeting_record'),
    path('advisor/projects/<int:project_id>/private-notes/', academic_views.private_note_add, name='private_note_add'),
    path('academic-files/<str:kind>/<int:file_id>/', academic_views.academic_file, name='academic_file'),
    path('proposals/<int:proposal_id>/withdraw/', views.student_proposal_withdraw, name='student_proposal_withdraw'),
    path(
        'tasks/<int:task_id>/submit/',
        views.student_task_submit,
        name='student_task_submit',
    ),
    path('advisor/', academic_views.advisor_center, name='advisor_home'),
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
