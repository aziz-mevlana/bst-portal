from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('verify-email/', views.verify_email_view, name='verify_email'),
    path('verify-email/resend/', views.resend_verification_view, name='resend_verification'),
    path('pending-approval/', views.pending_approval_view, name='pending_approval'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password-verify/', views.reset_password_verify_view, name='reset_password_verify'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
    path('profile/', views.profile_showcase_view, name='profile'),
    path('profile/<int:user_id>/', views.profile_showcase_view, name='user_profile'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    path('portfolio/settings/', views.portfolio_settings, name='portfolio_settings'),
    path('portfolio/approved-member-application/', views.approved_member_application_submit, name='approved_member_application_submit'),
    path('settings/account/', views.account_settings_update, name='account_settings_update'),
    path('settings/privacy/', views.privacy_settings_update, name='privacy_settings_update'),
    path('settings/password/', views.password_change, name='password_change'),
    path('settings/email/', views.email_change_request, name='email_change_request'),
    path('settings/email/reverify/', views.institutional_reverification_request, name='institutional_reverification_request'),
    path('settings/email/verify/', views.email_change_verify, name='email_change_verify'),
    path('users/<int:user_id>/report/', views.user_report_create, name='user_report_create'),
    path('portfolio/feedback/', views.portfolio_feedback, name='portfolio_feedback'),
    path('portfolio/certificates/add/', views.portfolio_certificate_add, name='portfolio_certificate_add'),
    path('portfolio/certificates/<int:certificate_id>/delete/', views.portfolio_certificate_delete, name='portfolio_certificate_delete'),
    path('portfolio/communication-preferences/', views.communication_preferences_update, name='communication_preferences_update'),
    path('privacy/requests/', views.data_subject_request_create, name='data_subject_request_create'),
]
