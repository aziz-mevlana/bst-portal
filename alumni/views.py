from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import AlumniProfile, AlumniExperience, Tag, SkillTag, Alumni, WorkExperience
from django.db import models
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect

@login_required
def alumni_list(request):
    alumni_list = Alumni.objects.filter(is_show_in_alumni_list=True)
    tags = SkillTag.objects.all()

    # Arama ve filtreleme parametreleri
    query = request.GET.get('q', '')
    experience_level = request.GET.get('experience_level', '')
    graduation_year = request.GET.get('graduation_year', '')
    tag_id = request.GET.get('tag', '')

    if query:
        alumni_list = alumni_list.filter(
            models.Q(user__username__icontains=query) |
            models.Q(user__first_name__icontains=query) |
            models.Q(user__last_name__icontains=query) |
            models.Q(current_position__icontains=query) |
            models.Q(company__icontains=query) |
            models.Q(bio__icontains=query)
        )
    if experience_level:
        alumni_list = alumni_list.filter(experience_level=experience_level)
    if graduation_year:
        alumni_list = alumni_list.filter(graduation_year=graduation_year)
    if tag_id:
        alumni_list = alumni_list.filter(skills__id=tag_id)

    # Mezuniyet yıllarını unique olarak al
    graduation_years = Alumni.objects.values_list('graduation_year', flat=True).distinct().order_by('-graduation_year')

    return render(request, 'alumni/alumni_list.html', {
        'alumni_list': alumni_list,
        'tags': tags,
        'graduation_years': graduation_years,
        'selected_experience_level': experience_level,
        'selected_graduation_year': graduation_year,
        'selected_tag': tag_id,
        'query': query,
    })

def alumni_detail(request, username):
    alumni = get_object_or_404(Alumni, user__username=username)
    experiences = alumni.work_experiences.all()
    if alumni.user.username == request.user.username:
        return redirect('alumni:alumni_profile')
    return render(request, 'alumni/alumni_detail.html', {
        'alumni': alumni,
        'experiences': experiences
    })

@login_required
def alumni_profile(request):
    try:
        profile = request.user.alumni
    except Alumni.DoesNotExist:
        messages.error(request, 'Mezun profiliniz bulunamadı.')
        return redirect('accounts:profile')
    
    experiences = profile.work_experiences.all()
    return render(request, 'alumni/alumni_profile.html', {
        'profile': profile,
        'experiences': experiences
    })

@login_required
def alumni_profile_edit(request):
    try:
        profile = request.user.alumni
    except Alumni.DoesNotExist:
        profile = Alumni(user=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_experience':
            return add_experience(request, profile)
        elif action == 'delete_experience':
            return delete_experience(request, profile)
        elif action == 'edit_experience':
            return edit_experience(request, profile)
        elif action == 'get_experience':
            return get_experience(request, profile)
        else:
            # Normal profile update
            profile.graduation_year = request.POST.get('graduation_year')
            profile.current_position = request.POST.get('current_position')
            profile.company = request.POST.get('company')
            profile.experience_level = request.POST.get('experience_level')
            profile.bio = request.POST.get('bio')
            profile.linkedin_url = request.POST.get('linkedin_url')
            profile.github_url = request.POST.get('github_url')
            profile.personal_website = request.POST.get('personal_website')
            profile.is_available_for_mentoring = request.POST.get('is_available_for_mentoring') == 'on'
            profile.is_show_in_alumni_list = request.POST.get('is_show_in_alumni_list') == 'on'
            
            # Etiketleri güncelle
            tag_ids = request.POST.getlist('tags')
            profile.skills.set(tag_ids)
            
            profile.save()
            messages.success(request, 'Profiliniz başarıyla güncellendi.')
            return redirect('alumni:alumni_profile')
    
    tags = SkillTag.objects.all()
    return render(request, 'alumni/alumni_profile_edit.html', {
        'profile': profile,
        'tags': tags
    })

def add_experience(request, profile):
    try:
        company = request.POST.get('company')
        position = request.POST.get('position')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_current = request.POST.get('is_current') == 'on'
        description = request.POST.get('description', '')
        
        if not company or not position or not start_date:
            return JsonResponse({'success': False, 'error': 'Zorunlu alanlar eksik'})
        
        experience = WorkExperience.objects.create(
            person=profile,
            company=company,
            position=position,
            start_date=start_date,
            end_date=end_date if not is_current else None,
            is_current=is_current,
            description=description
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def delete_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        experience.delete()
        return JsonResponse({'success': True})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def get_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        
        experience_data = {
            'id': experience.id,
            'company': experience.company,
            'position': experience.position,
            'start_date': experience.start_date,
            'end_date': experience.end_date,
            'is_current': experience.is_current,
            'description': experience.description
        }
        
        return JsonResponse({'success': True, 'experience': experience_data})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def edit_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        
        company = request.POST.get('company')
        position = request.POST.get('position')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_current = request.POST.get('is_current') == 'on'
        description = request.POST.get('description', '')
        
        if not company or not position or not start_date:
            return JsonResponse({'success': False, 'error': 'Zorunlu alanlar eksik'})
        
        experience.company = company
        experience.position = position
        experience.start_date = start_date
        experience.end_date = end_date if not is_current else None
        experience.is_current = is_current
        experience.description = description
        experience.save()
        
        return JsonResponse({'success': True})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def tag_list(request):
    tags = SkillTag.objects.all()
    return render(request, 'alumni/tag_list.html', {'tags': tags})
