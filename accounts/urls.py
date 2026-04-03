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
    path('profile/', views.profile_view, name='profile'),
    path('profile/<int:user_id>/', views.profile_view, name='user_profile'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
]