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
from datetime import datetime


def calculate_class_level(student_number):
    """Öğrenci numarasından sınıfı hesapla (örn: 23 -> 1.sınıf, 24 -> 1.sınıf)"""
    if not student_number or len(student_number) < 2:
        return '1'
    
    try:
        entry_year = int(student_number[:2])
        if entry_year >= 90:
            entry_year = 1900 + entry_year
        else:
            entry_year = 2000 + entry_year
        
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        if current_month >= 8:
            years_since_entry = current_year - entry_year + 1
        else:
            years_since_entry = current_year - entry_year
        
        if years_since_entry <= 0:
            return '1'
        elif years_since_entry == 1:
            return '1'
        elif years_since_entry == 2:
            return '2'
        elif years_since_entry == 3:
            return '3'
        elif years_since_entry == 4:
            return '4'
        else:
            return 'alt'
    except:
        return '1'


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        # Kullanıcıyı bul - duplicate email durumunda ilkini al
        try:
            user = User.objects.filter(email=email).order_by('-date_joined').first()
            if not user:
                messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
                return render(request, 'accounts/login.html')
        except Exception:
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
            return render(request, 'accounts/login.html')
        
        # Şifre kontrolü
        if not user.check_password(password):
            messages.error(request, 'Geçersiz kullanıcı adı veya şifre.')
            return render(request, 'accounts/login.html')
        
        # Öğretim üyesi ve inactive ise bekleme sayfasına
        try:
            if hasattr(user, 'profile') and user.profile.user_type == 'teacher' and not user.is_active:
                request.session['pending_teacher_email'] = user.email
                return redirect('accounts:pending_approval')
        except Exception:
            pass  # Profile doesn't exist, continue with login
        
        # Normal giriş
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
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

def logout_view(request):
    logout(request)
    messages.info(request, 'Başarıyla çıkış yaptınız.')
    return redirect('accounts:login')

def register_view(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        student_number = request.POST.get('student_number', '')
        password_1 = request.POST.get('password_1')
        password_2 = request.POST.get('password_2')
        user_type = request.POST.get('user_type', 'student')
        teacher_title = request.POST.get('teacher_title', '')

        # Öğretim üyesi için öğrenci numarası zorunlu değil
        if user_type != 'teacher':
            if not student_number:
                messages.error(request, 'Öğrenci numarası gereklidir.')
                return redirect('accounts:register')
            if len(student_number) != 10:
                messages.error(request, 'Öğrenci numarası 10 hane olmalıdır.')
                return redirect('accounts:register')
            if Profile.objects.filter(student_number=student_number).exists():
                messages.error(request, 'Bu öğrenci numarası zaten kayıtlı.')
                return redirect('accounts:register')
        
        if password_1 != password_2:
            messages.error(request, 'Şifreler eşleşmiyor.')
            return redirect('accounts:register')
        
        # Öğretim üyesi için email kontrolü
        if user_type == 'teacher':
            # Öğretim üyeleri için email kontrolü - daha esnek
            existing = User.objects.filter(email=email)
            if existing.exists():
                existing_user = existing.first()
                # Profile kontrolü
                try:
                    if hasattr(existing_user, 'profile') and existing_user.profile.user_type == 'teacher':
                        messages.error(request, 'Bu email zaten bir öğretim üyesi hesabına kayıtlı.')
                        return redirect('accounts:register')
                except Exception:
                    pass  # Profile doesn't exist, continue
        else:
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Bu email zaten kayıtlı.')
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
                    'user_type': user_type,
                    'teacher_title': teacher_title if user_type == 'teacher' else '',
                }
            )
        except Exception:
            messages.error(request, 'Bir hata oluştu. Lütfen tekrar deneyin.')
            return redirect('accounts:register')

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
        else:
            subject = 'BST Akademi - Email Doğrulama Kodu'
            message = f"""Merhaba {first_name},

Kayıt işlemini tamamlamak için doğrulama kodunuz: {code}

Bu kod 10 dakika geçerlidir.

BST Akademi
"""

        try:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            messages.info(request, f'{email} adresine doğrulama kodu gönderildi.')
        except Exception:
            messages.error(request, 'Doğrulama kodu gönderilemedi. Lütfen tekrar deneyin.')
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
        user_type = data.get('user_type', 'student')
        
        # Signal çalışmasın diye manually_created = True flag ekle
        user = User(
            username=data['username'],
            email=data['email'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            is_active=(user_type != 'teacher'),
        )
        user.set_password(data['password'])
        user._creating_profile = True  # Signal için flag
        user.save()
        
        # Profile oluştur - sınıfı otomatik hesapla
        student_number = data.get('student_number', '')
        class_level = calculate_class_level(student_number) if user_type == 'student' else None
        teacher_title = data.get('teacher_title', '')
        
        Profile.objects.create(
            user=user,
            user_type=user_type,
            teacher_title=teacher_title if user_type == 'teacher' else None,
            student_number=student_number,
            class_level=class_level or '1',
        )

        verification.delete()
        request.session.pop('verify_email', None)
        
        if user_type == 'teacher':
            request.session['pending_teacher_email'] = email
            messages.success(request, 'Kaydınız yapıldı. Yönetici onayı bekleniyor. Onaylandığında giriş yapabilirsiniz.')
            return redirect('accounts:pending_approval')
        else:
            messages.success(request, 'Kaydınız başarıyla tamamlandı. Giriş yapabilirsiniz.')
            return redirect('accounts:login')

    return render(request, 'accounts/verify_email.html', {'email': email})


def resend_verification_view(request):
    email = request.session.get('verify_email')
    if not email:
        messages.error(request, 'Oturum süresi dolmuş. Lütfen tekrar kayıt olun.')
        return redirect('accounts:register')
    
    verification = EmailVerification.objects.filter(email=email, is_verified=False).first()
    if not verification:
        messages.error(request, 'Doğrulama kaydı bulunamadı. Lütfen tekrar kayıt olun.')
        return redirect('accounts:register')
    
    code = EmailVerification.generate_code()
    verification.code = code
    verification.save()
    
    data = verification.session_data
    user_type = data.get('user_type', 'student')
    
    try:
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
        
        send_mail(
            subject,
            message,
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

        # Ensure profile exists
        profile, _ = Profile.objects.get_or_create(user=user)
        
        # Update class_level if provided
        class_level = request.POST.get('class_level')
        if class_level:
            profile.class_level = class_level
        
        # Update teacher_title if provided (for teachers)
        teacher_title = request.POST.get('teacher_title')
        if teacher_title is not None:
            profile.teacher_title = teacher_title if teacher_title != '' else None
        
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
                
            except Exception:
                messages.error(request, 'Profil fotoğrafı güncellenirken bir hata oluştu.')
        
        # Normal dosya yükleme (fallback)
        elif 'profile_picture_file' in request.FILES:
            try:
                profile.profile_picture = request.FILES['profile_picture_file']
                profile.save()
                messages.success(request, 'Profil fotoğrafı başarıyla güncellendi.')
            except Exception:
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
        profile.user_type = request.POST.get('user_type', profile.user_type)
        
        if profile.user_type == 'teacher':
            profile.teacher_title = request.POST.get('teacher_title', profile.teacher_title)
        
        profile.student_number = request.POST.get('student_number', profile.student_number)
        profile.class_level = request.POST.get('class_level', profile.class_level)
        profile.department = request.POST.get('department', profile.department)
        profile.phone_number = request.POST.get('phone_number', profile.phone_number)
        
        if 'profile_picture' in request.FILES:
            profile.profile_picture = request.FILES['profile_picture']
        
        profile.save()
        messages.success(request, 'Profiliniz başarıyla güncellendi.')
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile_edit.html')
