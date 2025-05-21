from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import AlumniProfile, AlumniExperience, Tag

def alumni_list(request):
    alumni_list = AlumniProfile.objects.all()
    tags = Tag.objects.all()
    return render(request, 'alumni/alumni_list.html', {
        'alumni_list': alumni_list,
        'tags': tags
    })

def alumni_detail(request, alumni_id):
    alumni = get_object_or_404(AlumniProfile, id=alumni_id)
    experiences = alumni.experiences.all()
    return render(request, 'alumni/alumni_detail.html', {
        'alumni': alumni,
        'experiences': experiences
    })

@login_required
def alumni_profile(request):
    try:
        profile = request.user.alumni_profile
    except AlumniProfile.DoesNotExist:
        messages.error(request, 'Mezun profiliniz bulunamadı.')
        return redirect('accounts:profile')
    
    experiences = profile.experiences.all()
    return render(request, 'alumni/alumni_profile.html', {
        'profile': profile,
        'experiences': experiences
    })

@login_required
def alumni_profile_edit(request):
    try:
        profile = request.user.alumni_profile
    except AlumniProfile.DoesNotExist:
        profile = AlumniProfile(user=request.user)
    
    if request.method == 'POST':
        profile.graduation_year = request.POST.get('graduation_year')
        profile.current_position = request.POST.get('current_position')
        profile.company = request.POST.get('company')
        profile.experience_level = request.POST.get('experience_level')
        profile.bio = request.POST.get('bio')
        profile.linkedin_url = request.POST.get('linkedin_url')
        profile.github_url = request.POST.get('github_url')
        profile.personal_website = request.POST.get('personal_website')
        profile.is_available_for_mentoring = request.POST.get('is_available_for_mentoring') == 'on'
        
        # Etiketleri güncelle
        tag_ids = request.POST.getlist('tags')
        profile.tags.set(tag_ids)
        
        profile.save()
        messages.success(request, 'Profiliniz başarıyla güncellendi.')
        return redirect('alumni:alumni_profile')
    
    tags = Tag.objects.all()
    return render(request, 'alumni/alumni_profile_edit.html', {
        'profile': profile,
        'tags': tags
    })

def tag_list(request):
    tags = Tag.objects.all()
    return render(request, 'alumni/tag_list.html', {'tags': tags})
