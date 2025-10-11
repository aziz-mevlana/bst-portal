from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from .models import UserProfile
from django.contrib.auth.models import User
import base64
from django.core.files.base import ContentFile

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
        if UserProfile.objects.filter(student_number=student_number).exists():
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
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password_1,
            first_name=first_name,
            last_name=last_name
        )
        # Profil zaten var mı kontrol et
        if not UserProfile.objects.filter(user=user).exists():
            UserProfile.objects.create(
                user=user,
                student_number=student_number
            )
        messages.success(request, 'Kayıt başarılı. Giriş yapabilirsiniz.')
        return redirect('accounts:login')
    return render(request, 'accounts/register.html')

@login_required
def profile_view(request):
    if request.method == 'POST':
        user = request.user
        user.email = request.POST.get('email', user.email)
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.save()

        profile = user.profile
        profile.bio = request.POST.get('bio', profile.bio)
        
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
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile.html')

@login_required
def profile_edit_view(request):
    if request.method == 'POST':
        profile = request.user.profile
        profile.user_type = request.POST.get('user_type', profile.user_type)
        profile.student_number = request.POST.get('student_number', profile.student_number)
        profile.department = request.POST.get('department', profile.department)
        profile.phone_number = request.POST.get('phone_number', profile.phone_number)
        profile.bio = request.POST.get('bio', profile.bio)
        
        if 'profile_picture' in request.FILES:
            profile.profile_picture = request.FILES['profile_picture']
        
        profile.save()
        messages.success(request, 'Profiliniz başarıyla güncellendi.')
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile_edit.html')
