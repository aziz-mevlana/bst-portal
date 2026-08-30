from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from .forms import (
    AccountSettingsForm, ApprovedMemberApplicationForm, EmailChangeForm, PrivacySettingsForm, UserReportForm,
    AccountDeletionForm, CommunicationPreferenceForm, DataSubjectRequestForm,
    PortfolioCertificateForm, PortfolioSettingsForm, SettingsPasswordChangeForm,
)
from .models import (
    CommunicationPreference, CommunityRegistration, ConsentRecord, DataSubjectRequest,
    PortfolioCertificate, Profile, EmailVerification, PasswordReset,
    UserReport,
)
from alumni.models import AlumniRegistrationRequest
from .email_service import EmailConfigurationError, send_transactional_email
from .validators import institutional_email_domain
from .permissions import ensure_interactive_account
from .image_utils import sanitize_profile_image
from django.contrib.auth.models import User
import base64
import binascii
import logging
from django.core.files.base import ContentFile
from projects.models import Project, ProjectCategory, Technology
from core.rate_limit import is_rate_limited
from core.audit import record_audit_event
from core.notifications import create_notification


logger = logging.getLogger(__name__)
PUBLIC_REGISTRATION_ROLES = {'student', 'teacher', 'alumni', 'other'}
MAX_CODE_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
LEGAL_TEXT_VERSION = '2026-08-13-v2'
_DUMMY_PASSWORD_HASH = make_password('bst-portal-login-timing-placeholder')


def _clear_password_reset_session(request):
    for key in (
        'reset_email', 'reset_decoy', 'reset_decoy_attempts',
        'reset_authorized_id', 'reset_verified',
    ):
        request.session.pop(key, None)


def _notify_approved_member_reviewers(application):
    reviewers = User.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True) | Q(profile__user_type='staff_student')
    ).distinct()
    for reviewer in reviewers:
        if reviewer.has_perm('accounts.review_contributor_applications'):
            create_notification(
                recipient=reviewer,
                actor=application.user,
                notification_type='pending_task',
                title='Yeni Onaylı Üye başvurusu',
                message=f'{application.user.get_full_name() or application.user.username} Onaylı Üye olmak istiyor.',
                target_url='/dashboard/approved-member-applications/',
                dedupe_key=f'approved-member-application:{application.pk}:{application.updated_at.timestamp()}',
                force=True,
            )


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        if (
            is_rate_limited(request, scope='login-ip', limit=20, window_seconds=300)
            or is_rate_limited(
                request, scope='login-account', limit=7, window_seconds=300,
                identifier=email,
            )
        ):
            messages.error(request, 'Çok fazla giriş denemesi yapıldı. Lütfen birkaç dakika sonra tekrar deneyin.')
            return render(request, 'accounts/login.html', status=429)
        
        # Kullanıcıyı bul - duplicate email durumunda ilkini al
        try:
            user = User.objects.filter(email__iexact=email).order_by('-date_joined').first()
            if not user:
                check_password(password, _DUMMY_PASSWORD_HASH)
                messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
                return render(request, 'accounts/login.html')
        except Exception:
            check_password(password, _DUMMY_PASSWORD_HASH)
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
            return render(request, 'accounts/login.html')
        
        # Şifre kontrolü
        if not user.check_password(password):
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
            return render(request, 'accounts/login.html')

        profile = getattr(user, 'profile', None)
        if profile and profile.account_status == 'suspended':
            if profile.suspended_until and profile.suspended_until <= timezone.now():
                profile.account_status = 'active'
                profile.suspension_reason = ''
                profile.suspended_until = None
                profile.save(update_fields=['account_status', 'suspension_reason', 'suspended_until'])
                user.is_active = True
                user.save(update_fields=['is_active'])
            else:
                messages.error(request, 'Hesabınız geçici olarak askıya alınmıştır. Destek için yöneticiyle iletişime geçin.')
                return render(request, 'accounts/login.html', status=403)
        if profile and profile.account_status == 'closed':
            messages.error(request, 'Bu hesap kapatılmıştır.')
            return render(request, 'accounts/login.html', status=403)
        
        # İnceleme bekleyen akademisyen ve mezunlar giriş yapmadan durum ekranını görür.
        try:
            if hasattr(user, 'profile') and user.profile.account_status == 'pending_review' and not user.is_active:
                request.session['pending_teacher_email'] = user.email
                return redirect('accounts:pending_approval')
        except Exception:
            pass  # Profile doesn't exist, continue with login
        
        # Normal giriş
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            if user.profile.must_change_password:
                messages.warning(request, 'Geçici şifrenizi kullanıyorsunuz. Devam etmek için yeni bir şifre belirleyin.')
                return redirect('accounts:portfolio_settings')
            messages.success(request, 'Başarıyla giriş yaptınız.')
            return redirect('portal:index')
        else:
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
    
    return render(request, 'accounts/login.html')


def pending_approval_view(request):
    email = request.session.get('pending_teacher_email')
    if not email:
        return redirect('accounts:login')
    return render(request, 'accounts/pending_approval.html', {'email': email})

@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, 'Başarıyla çıkış yaptınız.')
    return redirect('accounts:login')

def register_view(request):
    if request.method == 'POST':
        if is_rate_limited(request, scope='register', limit=5, window_seconds=3600):
            messages.error(request, 'Çok fazla kayıt denemesi yapıldı. Lütfen daha sonra tekrar deneyin.')
            return render(request, 'accounts/register.html', status=429)
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        student_number = request.POST.get('student_number', '').strip()
        class_level = request.POST.get('class_level', '').strip()
        graduation_year = request.POST.get('graduation_year', '').strip()
        password_1 = request.POST.get('password_1', '')
        password_2 = request.POST.get('password_2', '')
        user_type = request.POST.get('user_type', 'student')
        teacher_title = request.POST.get('teacher_title', '')
        accept_terms = request.POST.get('accept_terms') == 'on'
        privacy_notice_acknowledged = request.POST.get('privacy_notice_acknowledged') == 'on'
        marketing_consent = request.POST.get('marketing_consent') == 'on'
        if request.POST.get('website_check'):
            logger.warning('Kayıt honeypot alanı dolu gönderildi.')
            messages.error(request, 'Kayıt isteği doğrulanamadı.')
            return redirect('accounts:register')

        if not accept_terms or not privacy_notice_acknowledged:
            messages.error(request, 'Kayıt için kullanım koşullarını kabul etmeli ve KVKK aydınlatma metnini okumalısınız.')
            return redirect('accounts:register')

        if user_type not in PUBLIC_REGISTRATION_ROLES:
            logger.warning('Geçersiz kayıt rolü reddedildi: %s', user_type)
            messages.error(request, 'Geçersiz hesap türü seçildi.')
            return redirect('accounts:register')

        if not first_name or not last_name:
            messages.error(request, 'Ad ve soyad alanları zorunludur.')
            return redirect('accounts:register')

        try:
            validate_email(email)
            if user_type not in {'alumni', 'other'}:
                institutional_email_domain(email)
        except ValidationError:
            messages.error(request, 'Öğrenci ve akademisyen kaydı için @trakya.edu.tr kurumsal e-posta adresinizi kullanın.')
            return redirect('accounts:register')

        if user_type == 'student':
            if not student_number:
                messages.error(request, 'Öğrenci numarası gereklidir.')
                return redirect('accounts:register')
            if len(student_number) != 10 or not student_number.isdigit():
                messages.error(request, 'Öğrenci numarası 10 rakamdan oluşmalıdır.')
                return redirect('accounts:register')
            if Profile.objects.filter(student_number=student_number).exists():
                messages.error(request, 'Bu öğrenci numarası zaten kayıtlı.')
                return redirect('accounts:register')
            if class_level not in {'1', '2', '3', '4'}:
                messages.error(request, 'Geçerli bir sınıf seçmelisiniz.')
                return redirect('accounts:register')
        elif user_type == 'alumni':
            try:
                graduation_year_value = int(graduation_year)
            except (TypeError, ValueError):
                graduation_year_value = 0
            if graduation_year_value < 1980 or graduation_year_value > timezone.localdate().year:
                messages.error(request, 'Geçerli bir mezuniyet yılı girin.')
                return redirect('accounts:register')
            if student_number and (not student_number.isdigit() or len(student_number) > 20):
                messages.error(request, 'Öğrenci numarası yalnızca rakamlardan oluşmalıdır.')
                return redirect('accounts:register')
        
        if password_1 != password_2:
            messages.error(request, 'Şifreler eşleşmiyor.')
            return redirect('accounts:register')

        try:
            validate_password(password_1)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return redirect('accounts:register')

        if user_type == 'teacher':
            valid_titles = {value for value, _ in Profile.TEACHER_TITLE_CHOICES if value}
            if teacher_title and teacher_title not in valid_titles:
                messages.error(request, 'Geçersiz akademik ünvan seçildi.')
                return redirect('accounts:register')
        
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'Bu e-posta adresi zaten kayıtlı.')
            return redirect('accounts:register')

        # Username oluştur
        cleaned_first_name = first_name.strip().lower().replace(' ', '.')
        cleaned_last_name = last_name.strip().lower().replace(' ', '.')
        
        if student_number:
            part_student_number = student_number[1:3]  # 10. hane için [1:3] = 2. ve 3. rakam
            base_username = f"@{cleaned_first_name}{cleaned_last_name}{part_student_number}"
        else:
            base_username = f"@{cleaned_first_name}{cleaned_last_name}"
        
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        existing_verification = EmailVerification.objects.filter(
            email=email,
            is_verified=False,
        ).order_by('-created_at').first()
        if existing_verification:
            retry_after = RESEND_COOLDOWN_SECONDS - int(
                (timezone.now() - existing_verification.created_at).total_seconds()
            )
            if retry_after > 0:
                request.session['verify_email'] = email
                messages.info(request, f'Yeni kod istemek için {retry_after} saniye bekleyin.')
                return redirect('accounts:verify_email')

        code = EmailVerification.generate_code()
        verification_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'student_number': student_number,
            'class_level': class_level if user_type == 'student' else None,
            'graduation_year': graduation_year if user_type == 'alumni' else None,
            'username': username,
            'user_type': user_type,
            'teacher_title': teacher_title if user_type == 'teacher' else '',
            'legal_text_version': LEGAL_TEXT_VERSION,
            'accept_terms': accept_terms,
            'privacy_notice_acknowledged': privacy_notice_acknowledged,
            'marketing_consent': marketing_consent,
        }

        # Email içeriği user_type'a göre değişir
        if user_type == 'teacher':
            subject = 'BST Akademi - Akademisyen Kayıt Talebi'
            message = f"""Merhaba {first_name} {last_name},

BST Akademi'ye akademisyen olarak kayıt talebinde bulundunuz.

Doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.

Akademisyen kaydınız admin onayından geçecektir. Doğrulama sonrasında 
hesabınız admin tarafından aktif edildiğinde sisteme giriş yapabileceksiniz.

BST Akademi
"""
        elif user_type == 'alumni':
            subject = 'BST Akademi - Mezun Kayıt Talebi'
            message = f"""Merhaba {first_name} {last_name},

Mezun kayıt talebinizi tamamlamak için doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir. E-posta doğrulamasından sonra talebiniz BST yetkilileri tarafından incelenecektir.

BST Akademi
"""
        elif user_type == 'other':
            subject = 'BST Akademi - Topluluk Kaydı Doğrulama Kodu'
            message = f"""Merhaba {first_name},

BST Akademi topluluk kaydınızı tamamlamak için doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.

Hesabınız Ziyaretçi olarak açılacaktır. Dilerseniz giriş yaptıktan sonra profil ayarlarından Onaylı Üye başvurusu yapabilirsiniz.

BST Akademi
"""
        else:
            subject = 'BST Akademi - Email Doğrulama Kodu'
            message = f"""Merhaba {first_name},

Kayıt işlemini tamamlamak için doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.

BST Akademi
"""

        try:
            with transaction.atomic():
                EmailVerification.objects.filter(
                    email=email,
                    is_verified=False,
                ).delete()
                verification = EmailVerification(
                    email=email,
                    session_data=verification_data,
                    password_hash=make_password(password_1),
                )
                verification.set_code(code)
                verification.save()
                send_transactional_email(subject, message, email)
            messages.info(request, f'{email} adresine doğrulama kodu gönderildi.')
        except EmailConfigurationError:
            logger.exception('E-posta servisi yapılandırılmamış.')
            messages.error(
                request,
                'E-posta servisi yapılandırılmamış. Lütfen yöneticiye bildirin.',
            )
            return redirect('accounts:register')
        except Exception:
            logger.exception('Doğrulama e-postası gönderilemedi.')
            messages.error(request, 'Doğrulama kodu gönderilemedi. Lütfen tekrar deneyin.')
            return redirect('accounts:register')

        request.session['verify_email'] = email
        return redirect('accounts:verify_email')

    return render(request, 'accounts/register.html')


def verify_email_view(request):
    if request.method == 'POST' and is_rate_limited(request, scope='email-verify', limit=20, window_seconds=600):
        messages.error(request, 'Çok fazla doğrulama denemesi yapıldı. Lütfen daha sonra tekrar deneyin.')
        return redirect('accounts:verify_email')
    email = request.session.get('verify_email')
    if not email:
        messages.error(request, 'Önce kayıt formunu doldurun.')
        return redirect('accounts:register')

    verification = EmailVerification.objects.filter(email=email, is_verified=False).first()
    if not verification:
        messages.error(request, 'Doğrulama kodu bulunamadı. Lütfen tekrar kayıt olun.')
        request.session.pop('verify_email', None)
        return redirect('accounts:register')

    if request.method == 'POST':
        code = ''.join([
            request.POST.get(f'code_{i}', '') for i in range(1, 7)
        ])

        if verification.is_expired():
            verification.delete()
            messages.error(request, 'Doğrulama kodunun süresi doldu. Lütfen tekrar kayıt olun.')
            request.session.pop('verify_email', None)
            return redirect('accounts:register')

        if verification.failed_attempts >= MAX_CODE_ATTEMPTS:
            verification.delete()
            request.session.pop('verify_email', None)
            messages.error(request, 'Çok fazla hatalı deneme yapıldı. Lütfen yeniden kayıt olun.')
            return redirect('accounts:register')

        if not verification.matches_code(code):
            verification.failed_attempts += 1
            verification.save(update_fields=['failed_attempts'])
            remaining = MAX_CODE_ATTEMPTS - verification.failed_attempts
            if remaining <= 0:
                verification.delete()
                request.session.pop('verify_email', None)
                messages.error(request, 'Çok fazla hatalı deneme yapıldı. Lütfen yeniden kayıt olun.')
                return redirect('accounts:register')
            messages.error(request, f'Doğrulama kodu hatalı. {remaining} deneme hakkınız kaldı.')
            return redirect('accounts:verify_email')

        with transaction.atomic():
            verification = EmailVerification.objects.select_for_update().get(pk=verification.pk)
            data = verification.session_data
            user_type = data.get('user_type', 'student')
            if user_type not in PUBLIC_REGISTRATION_ROLES or not verification.password_hash:
                verification.delete()
                messages.error(request, 'Kayıt verisi geçersiz. Lütfen yeniden kayıt olun.')
                request.session.pop('verify_email', None)
                return redirect('accounts:register')

            profile_role = 'visitor' if user_type == 'other' else user_type
            user = User(
                username=data['username'],
                email=data['email'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                is_active=(user_type in {'student', 'other'}),
                password=verification.password_hash,
            )
            user._creating_profile = True
            user.save()

            student_number = data.get('student_number', '')
            class_level = data.get('class_level') if user_type == 'student' else None
            teacher_title = data.get('teacher_title', '')

            Profile.objects.create(
                user=user,
                user_type=profile_role,
                teacher_title=teacher_title if user_type == 'teacher' else None,
                student_number=student_number,
                class_level=class_level,
                institutional_email_verified_at=timezone.now() if user_type in {'student', 'teacher'} else None,
                graduation_year=int(data['graduation_year']) if user_type == 'alumni' else None,
                account_status='pending_review' if user_type in {'teacher', 'alumni'} else 'active',
            )
            if user_type == 'alumni':
                AlumniRegistrationRequest.objects.create(
                    user=user,
                    full_name=f"{data['first_name']} {data['last_name']}".strip(),
                    graduation_year=int(data['graduation_year']),
                    student_number=student_number,
                    email=data['email'],
                )
            legal_version = data.get('legal_text_version', LEGAL_TEXT_VERSION)
            ConsentRecord.objects.bulk_create([
                ConsentRecord(user=user, consent_type='terms', text_version=legal_version, accepted=True),
                ConsentRecord(user=user, consent_type='privacy_notice', text_version=legal_version, accepted=True),
                ConsentRecord(
                    user=user,
                    consent_type='marketing_email',
                    text_version=legal_version,
                    accepted=bool(data.get('marketing_consent', False)),
                ),
            ])
            CommunicationPreference.objects.create(
                user=user,
                email_announcements=bool(data.get('marketing_consent', False)),
            )
            verification.delete()
        request.session.pop('verify_email', None)
        
        if user_type in {'teacher', 'alumni'}:
            request.session['pending_teacher_email'] = email
            messages.success(request, 'Kaydınız yapıldı. Yönetici onayı bekleniyor. Onaylandığında giriş yapabilirsiniz.')
            return redirect('accounts:pending_approval')
        else:
            messages.success(request, 'Kaydınız başarıyla tamamlandı. Giriş yapabilirsiniz.')
            return redirect('accounts:login')

    return render(request, 'accounts/verify_email.html', {'email': email})


@require_POST
def resend_verification_view(request):
    if request.method == 'POST' and is_rate_limited(request, scope='email-resend', limit=5, window_seconds=600):
        messages.error(request, 'Çok fazla kod isteği yapıldı. Lütfen daha sonra tekrar deneyin.')
        return redirect('accounts:verify_email')
    email = request.session.get('verify_email')
    if not email:
        messages.error(request, 'Oturum süresi dolmuş. Lütfen tekrar kayıt olun.')
        return redirect('accounts:register')
    
    verification = EmailVerification.objects.filter(email=email, is_verified=False).first()
    if not verification:
        messages.error(request, 'Doğrulama kaydı bulunamadı. Lütfen tekrar kayıt olun.')
        return redirect('accounts:register')
    
    retry_after = RESEND_COOLDOWN_SECONDS - int(
        (timezone.now() - verification.created_at).total_seconds()
    )
    if retry_after > 0:
        messages.info(request, f'Yeni kod istemek için {retry_after} saniye bekleyin.')
        return redirect('accounts:verify_email')

    data = verification.session_data
    user_type = data.get('user_type', 'student')
    
    try:
        code = EmailVerification.generate_code()
        if user_type == 'teacher':
            subject = 'BST Akademi - Akademisyen Kayıt Talebi (Yeni Kod)'
            message = f"""Merhaba {data['first_name']} {data['last_name']},

BST Akademi'ye akademisyen olarak kayıt talebinde bulundunuz.

Yeni doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.
"""
        else:
            subject = 'BST Akademi - Doğrulama Kodu'
            message = f"""Merhaba {data['first_name']},

BST Akademi'ye hoş geldiniz!

Doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.
"""
        
        with transaction.atomic():
            verification = EmailVerification.objects.select_for_update().get(
                pk=verification.pk
            )
            verification.set_code(code)
            verification.created_at = timezone.now()
            verification.failed_attempts = 0
            verification.save(update_fields=['code', 'code_hash', 'created_at', 'failed_attempts'])
            send_transactional_email(subject, message, email)
        messages.success(request, 'Yeni doğrulama kodu gönderildi.')
    except EmailConfigurationError:
        logger.exception('E-posta servisi yapılandırılmamış.')
        messages.error(
            request,
            'E-posta servisi yapılandırılmamış. Lütfen yöneticiye bildirin.',
        )
    except Exception:
        logger.exception('Doğrulama e-postası yeniden gönderilemedi.')
        messages.error(request, 'Kod gönderilemedi. Lütfen tekrar deneyin.')
    
    return redirect('accounts:verify_email')


def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        if (
            is_rate_limited(request, scope='password-reset-request-ip', limit=10, window_seconds=3600)
            or is_rate_limited(
                request, scope='password-reset-request-account', limit=5,
                window_seconds=3600, identifier=email,
            )
        ):
            messages.error(request, 'Çok fazla şifre sıfırlama isteği yapıldı. Lütfen daha sonra tekrar deneyin.')
            return render(request, 'accounts/forgot_password.html', status=429)
        user = User.objects.filter(email__iexact=email).first()
        generic_message = (
            'Bu adres sistemde kayıtlıysa şifre sıfırlama kodu e-posta ile gönderildi.'
        )
        request.session['reset_email'] = email
        if user is None:
            request.session['reset_decoy'] = True
            request.session['reset_decoy_attempts'] = 0
            messages.info(request, generic_message)
            return redirect('accounts:reset_password_verify')

        request.session.pop('reset_decoy', None)
        request.session.pop('reset_decoy_attempts', None)

        code = PasswordReset.generate_code()

        existing_reset = PasswordReset.objects.filter(user=user, is_used=False).order_by('-created_at').first()
        if existing_reset:
            retry_after = RESEND_COOLDOWN_SECONDS - int(
                (timezone.now() - existing_reset.created_at).total_seconds()
            )
            if retry_after > 0:
                messages.info(request, generic_message)
                return redirect('accounts:reset_password_verify')

        try:
            with transaction.atomic():
                PasswordReset.objects.filter(user=user, is_used=False).delete()
                reset = PasswordReset(user=user)
                reset.set_code(code)
                reset.save()
                send_transactional_email(
                    'BST Akademi - Şifre Sıfırlama Kodu',
                    f'Merhaba {user.first_name},\n\nŞifre sıfırlama kodunuz: {code}\n\nBu kod 10 dakika geçerlidir.\n\nBST Akademi',
                    email,
                )
            messages.info(request, generic_message)
        except EmailConfigurationError:
            logger.exception('E-posta servisi yapılandırılmamış.')
            request.session['reset_decoy'] = True
            request.session['reset_decoy_attempts'] = 0
            messages.info(request, generic_message)
            return redirect('accounts:reset_password_verify')
        except Exception:
            logger.exception('Şifre sıfırlama e-postası gönderilemedi.')
            request.session['reset_decoy'] = True
            request.session['reset_decoy_attempts'] = 0
            messages.info(request, generic_message)
            return redirect('accounts:reset_password_verify')

        return redirect('accounts:reset_password_verify')

    return render(request, 'accounts/forgot_password.html')


def reset_password_verify_view(request):
    if request.method == 'POST' and is_rate_limited(request, scope='password-reset-verify', limit=20, window_seconds=600):
        messages.error(request, 'Çok fazla doğrulama denemesi yapıldı. Lütfen daha sonra tekrar deneyin.')
        return redirect('accounts:reset_password_verify')
    email = request.session.get('reset_email')
    if not email:
        messages.error(request, 'Önce email adresinizi girin.')
        return redirect('accounts:forgot_password')

    if request.session.get('reset_decoy'):
        if request.method == 'POST':
            attempts = int(request.session.get('reset_decoy_attempts', 0)) + 1
            request.session['reset_decoy_attempts'] = attempts
            if attempts >= MAX_CODE_ATTEMPTS:
                request.session.pop('reset_email', None)
                request.session.pop('reset_decoy', None)
                request.session.pop('reset_decoy_attempts', None)
                messages.error(request, 'Çok fazla hatalı deneme yapıldı. Yeni kod isteyin.')
                return redirect('accounts:forgot_password')
            messages.error(request, f'Kod hatalı. {MAX_CODE_ATTEMPTS - attempts} deneme hakkınız kaldı.')
            return redirect('accounts:reset_password_verify')
        return render(request, 'accounts/reset_password_verify.html', {'email': email})

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        request.session.pop('reset_email', None)
        messages.error(request, 'Kullanıcı bulunamadı.')
        return redirect('accounts:forgot_password')

    reset = PasswordReset.objects.filter(user=user, is_used=False).first()
    if not reset:
        messages.error(request, 'Sıfırlama kodu bulunamadı.')
        request.session.pop('reset_email', None)
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        code = ''.join([request.POST.get(f'code_{i}', '') for i in range(1, 7)])

        if reset.is_expired():
            reset.delete()
            messages.error(request, 'Kodun süresi doldu. Lütfen tekrar deneyin.')
            request.session.pop('reset_email', None)
            return redirect('accounts:forgot_password')

        if reset.failed_attempts >= MAX_CODE_ATTEMPTS:
            reset.delete()
            request.session.pop('reset_email', None)
            messages.error(request, 'Çok fazla hatalı deneme yapıldı. Yeni kod isteyin.')
            return redirect('accounts:forgot_password')

        if not reset.matches_code(code):
            reset.failed_attempts += 1
            reset.save(update_fields=['failed_attempts'])
            remaining = MAX_CODE_ATTEMPTS - reset.failed_attempts
            if remaining <= 0:
                reset.delete()
                request.session.pop('reset_email', None)
                messages.error(request, 'Çok fazla hatalı deneme yapıldı. Yeni kod isteyin.')
                return redirect('accounts:forgot_password')
            messages.error(request, f'Kod hatalı. {remaining} deneme hakkınız kaldı.')
            return redirect('accounts:reset_password_verify')

        request.session['reset_authorized_id'] = reset.pk
        return redirect('accounts:reset_password')

    return render(request, 'accounts/reset_password_verify.html', {'email': email})


def reset_password_view(request):
    email = request.session.get('reset_email')
    reset_id = request.session.get('reset_authorized_id')

    if not email or not reset_id:
        messages.error(request, 'Önce doğrulama adımını tamamlayın.')
        return redirect('accounts:forgot_password')

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        _clear_password_reset_session(request)
        messages.error(request, 'Kullanıcı bulunamadı.')
        return redirect('accounts:forgot_password')

    authorized_reset = PasswordReset.objects.filter(
        pk=reset_id, user=user, is_used=False,
    ).first()
    if not authorized_reset or authorized_reset.is_expired():
        _clear_password_reset_session(request)
        messages.error(request, 'Sıfırlama yetkisinin süresi doldu veya daha önce kullanıldı.')
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        password_1 = request.POST.get('password_1')
        password_2 = request.POST.get('password_2')

        if password_1 != password_2:
            messages.error(request, 'Şifreler eşleşmiyor.')
            return redirect('accounts:reset_password')

        try:
            validate_password(password_1, user=user)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return redirect('accounts:reset_password')

        with transaction.atomic():
            reset = PasswordReset.objects.select_for_update().filter(
                pk=reset_id, user=user, is_used=False,
            ).first()
            if not reset or reset.is_expired():
                _clear_password_reset_session(request)
                messages.error(request, 'Sıfırlama yetkisinin süresi doldu veya daha önce kullanıldı.')
                return redirect('accounts:forgot_password')

            consumed = PasswordReset.objects.filter(pk=reset.pk, is_used=False).update(is_used=True)
            if consumed != 1:
                _clear_password_reset_session(request)
                messages.error(request, 'Sıfırlama yetkisi daha önce kullanıldı.')
                return redirect('accounts:forgot_password')

            user.set_password(password_1)
            user.save(update_fields=['password'])
            if hasattr(user, 'profile') and user.profile.must_change_password:
                user.profile.must_change_password = False
                user.profile.save(update_fields=['must_change_password', 'updated_at'])
            PasswordReset.objects.filter(user=user, is_used=False).update(is_used=True)

        _clear_password_reset_session(request)

        messages.success(request, 'Şifreniz başarıyla sıfırlandı. Yeni şifrenizle giriş yapabilirsiniz.')
        return redirect('accounts:login')

    return render(request, 'accounts/reset_password.html')


@login_required
def profile_showcase_view(request, user_id=None):
    """Display and manage the projects a user deliberately puts on their profile."""

    if user_id is not None:
        view_user = get_object_or_404(User, id=user_id)
        is_own_profile = request.user == view_user
    else:
        view_user = request.user
        is_own_profile = True

    profile, _ = Profile.objects.get_or_create(user=view_user)
    eligible_projects = Project.objects.filter(
        Q(created_by=view_user)
        | Q(team=view_user)
        | Q(advisor=view_user)
        | Q(contributions__user=view_user, contributions__verified_by_owner=True)
    ).select_related('project_type', 'created_by').prefetch_related(
        'media', 'technologies', 'team'
    ).distinct().order_by('-updated_at')

    if request.method == 'POST':
        if not is_own_profile:
            return redirect('accounts:user_profile', user_id=view_user.id)
        requested_ids = set(request.POST.getlist('showcase_projects'))
        allowed_projects = eligible_projects.filter(pk__in=requested_ids)
        profile.showcase_projects.set(allowed_projects)
        messages.success(request, 'Proje serginiz güncellendi.')
        return redirect('accounts:profile')

    selected_projects = profile.showcase_projects.select_related(
        'project_type', 'created_by'
    ).prefetch_related('media', 'technologies', 'team').order_by('-updated_at')
    if not is_own_profile:
        selected_projects = selected_projects.filter(
            visibility='public',
            approval_status='approved',
        )

    return render(request, 'accounts/profile_showcase.html', {
        'view_user': view_user,
        'profile': profile,
        'is_own_profile': is_own_profile,
        'eligible_projects': eligible_projects if is_own_profile else Project.objects.none(),
        'selected_showcase_ids': set(profile.showcase_projects.values_list('pk', flat=True)),
        'selected_showcase_projects': selected_projects,
        'approved_member_application': CommunityRegistration.objects.filter(user=view_user).first(),
    })


@login_required
def profile_view(request, user_id=None):
    # Determine which user's profile to view
    if user_id is not None:
        view_user = get_object_or_404(User, id=user_id)
        is_own_profile = (request.user == view_user)
    else:
        view_user = request.user
        is_own_profile = True
    
    if request.method == 'POST':
        # Only allow editing if it's the user's own profile
        if not is_own_profile:
            return redirect('accounts:user_profile', user_id=view_user.id)
        
        # Update user information
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.save(update_fields=['first_name', 'last_name'])

        # Ensure profile exists
        profile, _ = Profile.objects.get_or_create(user=user)
        
        # Update class_level if provided
        class_level = request.POST.get('class_level')
        if profile.user_type in {'student', 'staff_student'} and class_level in {'1', '2', '3', '4'}:
            profile.class_level = class_level
        elif profile.user_type not in {'student', 'staff_student'}:
            profile.class_level = None
        
        # Update teacher_title if provided (for teachers)
        teacher_title = request.POST.get('teacher_title')
        valid_teacher_titles = {value for value, _ in Profile.TEACHER_TITLE_CHOICES}
        if profile.user_type == 'teacher' and teacher_title in valid_teacher_titles:
            profile.teacher_title = teacher_title or None
        
        # Base64 resim verisini işle
        cropped_image_data = request.POST.get('profile_picture')
        if cropped_image_data and cropped_image_data.startswith('data:image'):
            try:
                header, imgstr = cropped_image_data.split(';base64,', 1)
                if header not in {'data:image/jpeg', 'data:image/png', 'data:image/gif'}:
                    raise ValidationError('Desteklenmeyen görsel biçimi.')
                if len(imgstr) > 8 * 1024 * 1024:
                    raise ValidationError('Profil fotoğrafı en fazla 5 MB olabilir.')
                raw_upload = ContentFile(base64.b64decode(imgstr, validate=True), name='profile-upload')
                data = sanitize_profile_image(raw_upload)
                
                # Eski profil resmini sil
                if profile.profile_picture:
                    profile.profile_picture.delete(save=False)
                
                # Yeni resmi kaydet
                profile.profile_picture.save(data.name, data, save=True)
                messages.success(request, 'Profil fotoğrafı başarıyla güncellendi.')
            except (ValueError, binascii.Error, ValidationError):
                messages.error(request, 'Profil fotoğrafı güncellenirken bir hata oluştu.')
        
        # Normal dosya yükleme (fallback)
        elif 'profile_picture_file' in request.FILES:
            try:
                profile.profile_picture = sanitize_profile_image(request.FILES['profile_picture_file'])
                profile.save()
                messages.success(request, 'Profil fotoğrafı başarıyla güncellendi.')
            except ValidationError:
                messages.error(request, 'Dosya yüklenirken bir hata oluştu.')
        
        profile.save()
        
        # Save skills and technologies (only if editing own profile)
        if is_own_profile:
            category_ids = request.POST.getlist('categories')
            technology_ids = request.POST.getlist('technologies')
            profile.categories.set(category_ids)
            profile.technologies.set(technology_ids)
        
        return redirect('accounts:profile')
    
    # Get available categories and technologies for the form
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    
    return render(request, 'accounts/profile.html', {
        'view_user': view_user,
        'is_own_profile': is_own_profile,
        'categories': categories,
        'technologies': technologies,
    })

@login_required
def profile_edit_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        if profile.user_type == 'teacher':
            teacher_title = request.POST.get('teacher_title', profile.teacher_title)
            valid_teacher_titles = {value for value, _ in Profile.TEACHER_TITLE_CHOICES}
            if teacher_title not in valid_teacher_titles:
                messages.error(request, 'Geçerli bir akademik ünvan seçmelisiniz.')
                return redirect('accounts:profile')
            profile.teacher_title = teacher_title or None
        
        if profile.user_type in {'student', 'staff_student'}:
            profile.student_number = request.POST.get('student_number', profile.student_number)
            class_level = request.POST.get('class_level', '')
            if class_level not in {'1', '2', '3', '4'}:
                messages.error(request, 'Geçerli bir sınıf seçmelisiniz.')
                return redirect('accounts:profile')
            profile.class_level = class_level
        else:
            profile.class_level = None
        profile.department = request.POST.get('department', profile.department)
        profile.phone_number = request.POST.get('phone_number', profile.phone_number)
        
        if 'profile_picture' in request.FILES:
            try:
                profile.profile_picture = sanitize_profile_image(request.FILES['profile_picture'])
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
                return redirect('accounts:profile')
        
        profile.save()
        messages.success(request, 'Profiliniz başarıyla güncellendi.')
        return redirect('accounts:profile')
    
    return redirect('accounts:profile')


@login_required
def portfolio_settings(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = PortfolioSettingsForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Portfolyo ayarlarınız kaydedildi.')
            return redirect('accounts:portfolio_settings')
    else:
        form = PortfolioSettingsForm(instance=profile)
    communication_preferences, _ = CommunicationPreference.objects.get_or_create(user=request.user)
    approved_member_application = CommunityRegistration.objects.filter(user=request.user).first()
    return render(request, 'accounts/portfolio_settings.html', {
        'form': form,
        'certificate_form': PortfolioCertificateForm(),
        'certificates': profile.certificates.all(),
        'profile': profile,
        'communication_form': CommunicationPreferenceForm(instance=communication_preferences),
        'data_request_form': DataSubjectRequestForm(user=request.user),
        'account_deletion_form': AccountDeletionForm(user=request.user),
        'data_requests': request.user.data_subject_requests.all(),
        'account_form': AccountSettingsForm(user=request.user),
        'privacy_form': PrivacySettingsForm(instance=profile),
        'password_form': SettingsPasswordChangeForm(request.user),
        'email_change_form': EmailChangeForm(user=request.user),
        'moderation_history': request.user.moderation_actions.select_related('performed_by')[:10],
        'consent_records': request.user.consent_records.all()[:10],
        'approved_member_application': approved_member_application,
        'approved_member_application_form': ApprovedMemberApplicationForm(
            instance=(
                approved_member_application
                if approved_member_application and approved_member_application.status in {'visitor', 'rejected'}
                else None
            )
        ),
    })


@login_required
@require_POST
def approved_member_application_submit(request):
    ensure_interactive_account(request.user)
    if request.user.profile.user_type != 'visitor':
        raise PermissionDenied

    with transaction.atomic():
        application = CommunityRegistration.objects.select_for_update().filter(user=request.user).first()
        if application and application.status == 'pending':
            messages.info(request, 'Onaylı Üye başvurunuz zaten incelemede.')
            return redirect(f"{reverse('accounts:portfolio_settings')}#approved-member")
        if application and application.status == 'approved':
            messages.info(request, 'Hesabınız zaten Onaylı Üye.')
            return redirect(f"{reverse('accounts:portfolio_settings')}#approved-member")

        form = ApprovedMemberApplicationForm(request.POST, instance=application)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect(f"{reverse('accounts:portfolio_settings')}#approved-member")

        application = form.save(commit=False)
        application.user = request.user
        application.wants_to_share = True
        application.status = 'pending'
        application.reviewer_note = ''
        application.reviewed_by = None
        application.reviewed_at = None
        application.save()
        transaction.on_commit(
            lambda submitted_application=application: _notify_approved_member_reviewers(submitted_application)
        )

    messages.success(request, 'Onaylı Üye başvurunuz incelemeye gönderildi.')
    return redirect(f"{reverse('accounts:portfolio_settings')}#approved-member")


@login_required
@require_POST
def account_settings_update(request):
    form = AccountSettingsForm(request.POST, request.FILES, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, 'Hesap bilgileriniz güncellendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def privacy_settings_update(request):
    form = PrivacySettingsForm(request.POST, instance=request.user.profile)
    if form.is_valid():
        form.save()
        messages.success(request, 'Gizlilik tercihleriniz güncellendi.')
    else:
        messages.error(request, 'Gizlilik tercihleri güncellenemedi.')
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def password_change(request):
    if is_rate_limited(request, scope='password-change', limit=5, window_seconds=3600):
        messages.error(request, 'Çok fazla şifre değiştirme denemesi yapıldı.')
        return redirect('accounts:portfolio_settings')
    form = SettingsPasswordChangeForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        if user.profile.must_change_password:
            user.profile.must_change_password = False
            user.profile.save(update_fields=['must_change_password', 'updated_at'])
        update_session_auth_hash(request, user)
        record_audit_event(actor=user, action='account.password_changed', target=user, request=request)
        messages.success(request, 'Şifreniz güvenli biçimde değiştirildi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def email_change_request(request):
    if is_rate_limited(request, scope='email-change', limit=5, window_seconds=3600):
        messages.error(request, 'Çok fazla e-posta değiştirme isteği yapıldı.')
        return redirect('accounts:portfolio_settings')
    form = EmailChangeForm(request.POST, user=request.user)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('accounts:portfolio_settings')
    new_email = form.cleaned_data['new_email']
    code = EmailVerification.generate_code()
    try:
        with transaction.atomic():
            verification = EmailVerification(
                email=new_email,
                session_data={'purpose': 'email_change', 'user_id': request.user.pk},
            )
            verification.set_code(code)
            verification.save()
            send_transactional_email(
                'BST Akademi - Yeni e-posta doğrulama kodu',
                f'Merhaba {request.user.first_name or request.user.username},\n\nYeni e-posta adresinizi doğrulamak için kodunuz: {code}\n\nKod 10 dakika geçerlidir.',
                new_email,
            )
    except Exception:
        logger.exception('E-posta değiştirme doğrulaması gönderilemedi.')
        messages.error(request, 'Doğrulama e-postası gönderilemedi.')
        return redirect('accounts:portfolio_settings')
    request.session['email_change_verification_id'] = verification.pk
    return redirect('accounts:email_change_verify')


@login_required
@require_POST
def institutional_reverification_request(request):
    try:
        institutional_email_domain(request.user.email)
    except ValidationError:
        messages.error(request, 'Mevcut adresiniz kurumsal değil. Önce yeni bir @trakya.edu.tr adresi girin.')
        return redirect('accounts:portfolio_settings')
    if is_rate_limited(request, scope='institutional-reverify', limit=5, window_seconds=3600):
        messages.error(request, 'Çok fazla doğrulama kodu istendi.')
        return redirect('accounts:portfolio_settings')
    code = EmailVerification.generate_code()
    try:
        with transaction.atomic():
            verification = EmailVerification(
                email=request.user.email,
                session_data={'purpose': 'institutional_reverify', 'user_id': request.user.pk},
            )
            verification.set_code(code)
            verification.save()
            send_transactional_email(
                'BST Akademi - Kurumsal e-posta doğrulama kodu',
                f'Kurumsal e-posta doğrulama kodunuz: {code}\n\nKod 10 dakika geçerlidir.',
                request.user.email,
            )
    except Exception:
        logger.exception('Kurumsal yeniden doğrulama e-postası gönderilemedi.')
        messages.error(request, 'Doğrulama e-postası gönderilemedi.')
        return redirect('accounts:portfolio_settings')
    request.session['email_change_verification_id'] = verification.pk
    return redirect('accounts:email_change_verify')


@login_required
def email_change_verify(request):
    verification_id = request.session.get('email_change_verification_id')
    verification = EmailVerification.objects.filter(pk=verification_id, is_verified=False).first()
    purpose = verification.session_data.get('purpose') if verification else None
    if not verification or purpose not in {'email_change', 'institutional_reverify'} or verification.session_data.get('user_id') != request.user.pk:
        messages.error(request, 'E-posta değiştirme doğrulaması bulunamadı.')
        return redirect('accounts:portfolio_settings')
    if request.method == 'POST':
        if verification.is_expired() or verification.failed_attempts >= MAX_CODE_ATTEMPTS:
            messages.error(request, 'Doğrulama kodunun süresi doldu veya deneme sınırı aşıldı.')
            return redirect('accounts:portfolio_settings')
        code = request.POST.get('code', '').strip()
        if not verification.matches_code(code):
            verification.failed_attempts += 1
            verification.save(update_fields=['failed_attempts'])
            messages.error(request, 'Doğrulama kodu hatalı.')
            return redirect('accounts:email_change_verify')
        if User.objects.exclude(pk=request.user.pk).filter(email__iexact=verification.email).exists():
            messages.error(request, 'Bu e-posta adresi artık başka bir hesapta kullanılıyor.')
            return redirect('accounts:portfolio_settings')
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if purpose == 'email_change':
                user.email = verification.email
                user.save(update_fields=['email'])
            profile = user.profile
            profile.institutional_email_verified_at = timezone.now()
            if profile.account_status == 'pending_email':
                profile.account_status = 'active'
            profile.save(update_fields=['institutional_email_verified_at', 'account_status'])
            verification.is_verified = True
            verification.save(update_fields=['is_verified'])
        request.session.pop('email_change_verification_id', None)
        audit_action = 'account.email_changed' if purpose == 'email_change' else 'account.email_reverified'
        record_audit_event(actor=request.user, action=audit_action, target=request.user, request=request)
        messages.success(request, 'E-posta adresiniz doğrulandı ve değiştirildi.' if purpose == 'email_change' else 'Kurumsal e-posta adresiniz doğrulandı.')
        return redirect('accounts:portfolio_settings')
    return render(request, 'accounts/email_change_verify.html', {'email': verification.email})


@login_required
@require_POST
def user_report_create(request, user_id):
    reported_user = get_object_or_404(User, pk=user_id)
    if reported_user == request.user:
        raise PermissionDenied
    if is_rate_limited(request, scope='user-report', limit=5, window_seconds=86400):
        messages.error(request, 'Günlük şikâyet sınırına ulaştınız.')
        return redirect('accounts:user_profile', user_id=user_id)
    form = UserReportForm(request.POST)
    if form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.reported_user = reported_user
        report.save()
        messages.success(request, 'Şikâyetiniz yöneticilere iletildi.')
    else:
        messages.error(request, 'Şikâyet gönderilemedi.')
    return redirect('accounts:user_profile', user_id=user_id)


@login_required
def portfolio_feedback(request):
    from .portfolio_feedback import build_portfolio_feedback

    profile, _ = Profile.objects.get_or_create(user=request.user)
    feedback = build_portfolio_feedback(request.user)
    return render(request, 'accounts/portfolio_feedback.html', {
        'profile': profile,
        'feedback': feedback,
    })


@login_required
@require_POST
def portfolio_certificate_add(request):
    form = PortfolioCertificateForm(request.POST)
    if form.is_valid():
        certificate = form.save(commit=False)
        certificate.profile = request.user.profile
        certificate.save()
        messages.success(request, 'Sertifika portfolyonuza eklendi.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def portfolio_certificate_delete(request, certificate_id):
    certificate = get_object_or_404(
        PortfolioCertificate,
        pk=certificate_id,
        profile=request.user.profile,
    )
    certificate.delete()
    messages.success(request, 'Sertifika kaldırıldı.')
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def communication_preferences_update(request):
    preferences, _ = CommunicationPreference.objects.get_or_create(user=request.user)
    form = CommunicationPreferenceForm(request.POST, instance=preferences)
    if form.is_valid():
        form.save()
        ConsentRecord.objects.create(
            user=request.user,
            consent_type='marketing_email',
            text_version=LEGAL_TEXT_VERSION,
            accepted=preferences.email_announcements,
        )
        messages.success(request, 'İletişim tercihleriniz güncellendi.')
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def data_subject_request_create(request):
    form = DataSubjectRequestForm(request.POST, user=request.user)
    if form.is_valid():
        data_request = form.save(commit=False)
        data_request.user = request.user
        try:
            with transaction.atomic():
                data_request.save()
        except IntegrityError:
            messages.error(request, 'Bu türde açık bir talebiniz zaten bulunuyor.')
        else:
            messages.success(request, 'Veri talebiniz incelemeye alındı.')
    else:
        messages.error(request, 'Veri talebi oluşturulamadı.')
    return redirect('accounts:portfolio_settings')


@login_required
@require_POST
def visitor_account_delete(request):
    user = request.user
    profile = getattr(user, 'profile', None)
    if user.is_staff or user.is_superuser or not profile or profile.user_type != 'visitor':
        raise PermissionDenied

    form = AccountDeletionForm(request.POST, user=user)
    if not form.is_valid():
        messages.error(request, 'Hesap silinemedi. Mevcut parolanızı ve onay kutusunu kontrol edin.')
        return redirect(f"{reverse('accounts:portfolio_settings')}#data")

    try:
        with transaction.atomic():
            DataSubjectRequest.objects.filter(user=user).delete()
            ConsentRecord.objects.filter(user=user).delete()
            record_audit_event(
                actor=user,
                action='account.deleted_by_visitor',
                target=user,
                request=request,
                metadata={'user_type': 'visitor'},
            )
            user.delete()
    except ProtectedError:
        messages.error(
            request,
            'Hesap güvenlik veya moderasyon kayıtlarıyla bağlantılı olduğu için otomatik silinemedi. Lütfen yönetimle iletişime geçin.',
        )
        return redirect(f"{reverse('accounts:portfolio_settings')}#data")

    logout(request)
    messages.success(request, 'Ziyaretçi hesabınız ve hesabınıza bağlı içerikler kalıcı olarak silindi.')
    return redirect('portal:index')
