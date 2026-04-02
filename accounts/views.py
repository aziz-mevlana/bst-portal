from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.core.mail import send_mail
from django.conf import settings
from .models import Profile, EmailVerification, PasswordReset
from django.contrib.auth.models import User
import base64
from django.core.files.base import ContentFile
from django.http import Http404
from projects.models import ProjectCategory, Technology

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, email=email, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, 'Başarıyla giriş yaptınız.')
            return redirect('portal:index')
        else:
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
    
    return render(request, 'accounts/login.html')

def logout_view(request):
    logout(request)
    messages.info(request, 'Başarıyla çıkış yaptınız.')
    return redirect('accounts:login')

def register_view(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        student_number = request.POST.get('student_number')
        password_1 = request.POST.get('password_1')
        password_2 = request.POST.get('password_2')

        if Profile.objects.filter(student_number=student_number).exists():
            messages.error(request, 'Bu öğrenci numarası zaten kayıtlı.')
            return redirect('accounts:register')
        if password_1 != password_2:
            messages.error(request, 'Şifreler eşleşmiyor.')
            return redirect('accounts:register')
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Bu email zaten kayıtlı.')
            return redirect('accounts:register')

        cleaned_first_name = first_name.strip().lower().replace(' ', '.')
        cleaned_last_name = last_name.strip().lower().replace(' ', '.')
        part_student_number = student_number[1:3]
        base_username = f"@{cleaned_first_name}{cleaned_last_name}{part_student_number}"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{student_number[-2:]}{counter}"
            counter += 1

        try:
            code = EmailVerification.generate_code()
            EmailVerification.objects.filter(email=email, is_verified=False).delete()
            EmailVerification.objects.create(
                email=email,
                code=code,
                session_data={
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'student_number': student_number,
                    'password': password_1,
                    'username': username,
                }
            )
        except Exception as e:
            messages.error(request, f'Veritabanı hatası: {e}')
            return redirect('accounts:register')

        try:
            send_mail(
                'BST Akademi - Email Doğrulama Kodu',
                f'Merhaba {first_name},\n\nKayıt işlemini tamamlamak için doğrulama kodunuz: {code}\n\nBu kod 10 dakika geçerlidir.\n\nBST Akademi',
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            messages.info(request, f'{email} adresine doğrulama kodu gönderildi.')
        except Exception as e:
            messages.error(request, f'Mail gönderilemedi: {e}')
            return redirect('accounts:register')

        request.session['verify_email'] = email
        return redirect('accounts:verify_email')

    return render(request, 'accounts/register.html')


def verify_email_view(request):
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

        if code != verification.code:
            messages.error(request, 'Doğrulama kodu hatalı.')
            return redirect('accounts:verify_email')

        data = verification.session_data
        user = User.objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            first_name=data['first_name'],
            last_name=data['last_name'],
        )
        if not Profile.objects.filter(user=user).exists():
            Profile.objects.create(
                user=user,
                student_number=data['student_number'],
            )

        verification.is_verified = True
        verification.save()

        request.session.pop('verify_email', None)
        messages.success(request, 'Kayıt başarılı. Giriş yapabilirsiniz.')
        return redirect('accounts:login')

    return render(request, 'accounts/verify_email.html', {'email': email})


def resend_code_view(request):
    email = request.session.get('verify_email')
    if not email:
        messages.error(request, 'Önce kayıt formunu doldurun.')
        return redirect('accounts:register')

    verification = EmailVerification.objects.filter(email=email, is_verified=False).first()
    if not verification:
        messages.error(request, 'Doğrulama kaydı bulunamadı.')
        request.session.pop('verify_email', None)
        return redirect('accounts:register')

    code = EmailVerification.generate_code()
    verification.code = code
    verification.save()

    try:
        send_mail(
            'BST Akademi - Yeni Doğrulama Kodu',
            f'Merhaba,\n\nYeni doğrulama kodunuz: {code}\n\nBu kod 10 dakika geçerlidir.\n\nBST Akademi',
            settings.EMAIL_HOST_USER,
            [email],
            fail_silently=False,
        )
        messages.success(request, 'Yeni doğrulama kodu gönderildi.')
    except Exception:
        messages.error(request, 'Kod gönderilemedi. Lütfen tekrar deneyin.')

    return redirect('accounts:verify_email')


def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, 'Bu email adresi ile kayıtlı hesap bulunamadı.')
            return redirect('accounts:forgot_password')

        PasswordReset.objects.filter(user=user, is_used=False).delete()
        code = PasswordReset.generate_code()
        PasswordReset.objects.create(user=user, code=code)

        try:
            send_mail(
                'BST Akademi - Şifre Sıfırlama Kodu',
                f'Merhaba {user.first_name},\n\nŞifre sıfırlama kodunuz: {code}\n\nBu kod 10 dakika geçerlidir.\n\nBST Akademi',
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            messages.info(request, f'{email} adresine sıfırlama kodu gönderildi.')
        except Exception:
            messages.error(request, 'Kod gönderilemedi. Lütfen tekrar deneyin.')
            return redirect('accounts:forgot_password')

        request.session['reset_email'] = email
        return redirect('accounts:reset_password_verify')

    return render(request, 'accounts/forgot_password.html')


def reset_password_verify_view(request):
    email = request.session.get('reset_email')
    if not email:
        messages.error(request, 'Önce email adresinizi girin.')
        return redirect('accounts:forgot_password')

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

        if code != reset.code:
            messages.error(request, 'Kod hatalı.')
            return redirect('accounts:reset_password_verify')

        request.session['reset_verified'] = True
        return redirect('accounts:reset_password')

    return render(request, 'accounts/reset_password_verify.html', {'email': email})


def reset_password_view(request):
    email = request.session.get('reset_email')
    verified = request.session.get('reset_verified')

    if not email or not verified:
        messages.error(request, 'Önce doğrulama adımını tamamlayın.')
        return redirect('accounts:forgot_password')

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        request.session.pop('reset_email', None)
        request.session.pop('reset_verified', None)
        messages.error(request, 'Kullanıcı bulunamadı.')
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        password_1 = request.POST.get('password_1')
        password_2 = request.POST.get('password_2')

        if password_1 != password_2:
            messages.error(request, 'Şifreler eşleşmiyor.')
            return redirect('accounts:reset_password')

        if len(password_1) < 6:
            messages.error(request, 'Şifre en az 6 karakter olmalı.')
            return redirect('accounts:reset_password')

        user.set_password(password_1)
        user.save()

        PasswordReset.objects.filter(user=user).update(is_used=True)

        request.session.pop('reset_email', None)
        request.session.pop('reset_verified', None)

        messages.success(request, 'Şifreniz başarıyla sıfırlandı. Yeni şifrenizle giriş yapabilirsiniz.')
        return redirect('accounts:login')

    return render(request, 'accounts/reset_password.html')


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
        user.email = request.POST.get('email', user.email)
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.save()

        profile = user.profile        
        # Base64 resim verisini işle
        cropped_image_data = request.POST.get('profile_picture')
        if cropped_image_data and cropped_image_data.startswith('data:image'):
            try:
                # Formatı doğru şekilde ayır
                format, imgstr = cropped_image_data.split(';base64,')
                ext = format.split('/')[-1]
                
                # Desteklenen format kontrolü
                if ext not in ['jpeg', 'png', 'gif']:
                    ext = 'jpeg'  # Varsayılan format
                
                # Base64'ü decode et ve dosya oluştur
                data = ContentFile(base64.b64decode(imgstr))
                file_name = f'profile_{user.id}.{ext}'
                
                # Eski profil resmini sil
                if profile.profile_picture:
                    profile.profile_picture.delete(save=False)
                
                # Yeni resmi kaydet
                profile.profile_picture.save(file_name, data, save=True)
                messages.success(request, 'Profil fotoğrafı başarıyla güncellendi.')
                
            except Exception as e:
                messages.error(request, f'Profil fotoğrafı güncellenirken hata oluştu: {str(e)}')
        
        # Normal dosya yükleme (fallback)
        elif 'profile_picture_file' in request.FILES:
            try:
                profile.profile_picture = request.FILES['profile_picture_file']
                profile.save()
                messages.success(request, 'Profil fotoğrafı başarıyla güncellendi.')
            except Exception as e:
                messages.error(request, f'Dosya yüklenirken hata oluştu: {str(e)}')
        
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
    if request.method == 'POST':
        profile = request.user.profile
        profile.user_type = request.POST.get('user_type', profile.user_type)
        profile.student_number = request.POST.get('student_number', profile.student_number)
        profile.department = request.POST.get('department', profile.department)
        profile.phone_number = request.POST.get('phone_number', profile.phone_number)
        
        if 'profile_picture' in request.FILES:
            profile.profile_picture = request.FILES['profile_picture']
        
        profile.save()
        messages.success(request, 'Profiliniz başarıyla güncellendi.')
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile_edit.html')
