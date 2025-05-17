from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from .models import UserProfile

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, 'Başarıyla giriş yaptınız.')
            return redirect('events:event_list')
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
            return redirect('accounts:profile_edit')
    else:
        form = UserCreationForm()
    
    return render(request, 'accounts/register.html', {'form': form})

@login_required
def profile_view(request):
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
