from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from .models import UserProfile
import base64
from django.core.files.base import ContentFile

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
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
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Hesabınız başarıyla oluşturuldu.')
            return redirect('accounts:profile')
    else:
        form = UserCreationForm()
    
    return render(request, 'accounts/register.html', {'form': form})

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
