from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from django.http import JsonResponse

from projects.models import ProjectCategory, Technology

from .models import Alumni, WorkExperience

PAGE_SIZE = 12


def load_more_alumni(request):
    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    experience_level = request.GET.get('experience_level', '')
    graduation_year = request.GET.get('graduation_year', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')

    alumni_qs = Alumni.objects.filter(is_show_in_alumni_list=True).prefetch_related(
        'categories', 'technologies', 'user__profile'
    )

    if query:
        alumni_qs = alumni_qs.filter(
            models.Q(user__username__icontains=query) |
            models.Q(user__first_name__icontains=query) |
            models.Q(user__last_name__icontains=query) |
            models.Q(current_position__icontains=query) |
            models.Q(company__icontains=query) |
            models.Q(bio__icontains=query)
        )
    if experience_level:
        alumni_qs = alumni_qs.filter(experience_level=experience_level)
    if graduation_year:
        alumni_qs = alumni_qs.filter(graduation_year=graduation_year)
    if category_id:
        alumni_qs = alumni_qs.filter(categories__id=category_id)
    if technology_id:
        alumni_qs = alumni_qs.filter(technologies__id=technology_id)

    alumni_qs = alumni_qs.distinct()
    alumni = list(alumni_qs[offset:offset + PAGE_SIZE])
    has_more = len(alumni) == PAGE_SIZE

    items = []
    for alumni_obj in alumni:
        profile_picture = alumni_obj.user.profile.profile_picture.url if hasattr(alumni_obj.user, 'profile') and alumni_obj.user.profile.profile_picture else '/static/images/icons/profile.svg'
        
        badges = f'''
        <span class="alumni-badge px-2 py-1 rounded-full text-xs font-semibold" 
              style="--badge-bg: #FFFFFF20; --badge-color: #FFFFFF; --badge-border: #FFFFFF40;" 
              data-badge-color="#FFFFFF">
            {alumni_obj.graduation_year}
        </span>
        <span class="alumni-badge px-2 py-1 rounded-full text-xs font-semibold" 
              style="--badge-bg: #3B82F620; --badge-color: #3B82F6; --badge-border: #3B82F640;" 
              data-badge-color="#3B82F6">
            {alumni_obj.get_experience_level_display()}
        </span>
        '''
        
        if alumni_obj.is_available_for_mentoring:
            badges += '''
        <span class="alumni-badge px-2 py-1 rounded-full text-xs font-semibold" 
              style="--badge-bg: #10B98120; --badge-color: #10B981; --badge-border: #10B98140;" 
              data-badge-color="#10B981">
            Mentor
        </span>
            '''

        for category in alumni_obj.categories.all():
            badges += f'''
        <span class="alumni-skill-tag px-2 py-1 rounded-full text-xs font-semibold" 
              style="--skill-bg: {category.color}20; --skill-color: {category.color}; --skill-border: {category.color}40;" 
              data-skill-color="{category.color}">
            {category.name}
        </span>
            '''

        for technology in alumni_obj.technologies.all():
            badges += f'''
        <span class="alumni-skill-tag px-2 py-1 rounded-full text-xs font-semibold" 
              style="--skill-bg: {technology.color}20; --skill-color: {technology.color}; --skill-border: {technology.color}40;" 
              data-skill-color="{technology.color}">
            {technology.name}
        </span>
            '''

        social_icons = ''
        if alumni_obj.linkedin_url:
            social_icons += f'<a href="{alumni_obj.linkedin_url}" target="_blank" title="LinkedIn" class="hover:scale-110 transition"><img src="/static/images/icons/linkedin.svg" alt="LinkedIn" width="20" height="20"></a>'
        if alumni_obj.github_url:
            social_icons += f'<a href="{alumni_obj.github_url}" target="_blank" title="GitHub" class="hover:scale-110 transition"><img src="/static/images/icons/github.svg" alt="GitHub" width="20" height="20"></a>'
        if alumni_obj.personal_website:
            social_icons += f'<a href="{alumni_obj.personal_website}" target="_blank" title="Web" class="hover:scale-110 transition"><img src="/static/images/icons/external-link.svg" alt="Web" width="20" height="20"></a>'

        items.append(f'''
        <div class="project-list-card rounded-xl shadow-lg hover:shadow-2xl transition p-5 flex flex-col justify-between h-full">
            <a href="/alumni/{alumni_obj.user.username}/">
                <div class="flex flex-col sm:flex-row sm:items-start gap-4 mb-4">
                    <div class="shrink-0 mx-auto sm:mx-0">
                        <img src="{profile_picture}" alt="{alumni_obj.user.username}" class="w-20 h-20 sm:w-24 sm:h-24 object-cover rounded-full alumni-list-profile-picture">
                    </div>
                    <div class="flex-1 text-center sm:text-left space-y-1">
                        <h3 class="text-lg sm:text-xl font-bold">{alumni_obj.user.get_full_name()}</h3>
                        <div class="text-xs sm:text-sm text-gray-400">{alumni_obj.current_position} @ {alumni_obj.company}</div>
                    </div>
                </div>
                <div class="flex flex-wrap gap-1.5 justify-center sm:justify-start mb-4">
                    {badges}
                </div>
            </a>
            <div class="flex flex-col sm:flex-row items-center justify-between border-t border-gray-600 pt-3 mt-auto gap-2">
                <div class="flex items-center gap-3 alumni-list-social-media-icons">
                    {social_icons}
                </div>
                <div class="text-gray-400 text-xs sm:text-sm truncate max-w-[200px] sm:max-w-none">{alumni_obj.user.email}</div>
            </div>
        </div>
        ''')

    return JsonResponse({
        'items': ''.join(items),
        'has_more': has_more,
        'next_offset': offset + PAGE_SIZE if has_more else 0
    })


@login_required
def alumni_list(request):
    alumni_list = Alumni.objects.filter(is_show_in_alumni_list=True).prefetch_related(
        'categories', 'technologies', 'user__profile'
    )
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()

    # Arama ve filtreleme parametreleri
    query = request.GET.get('q', '')
    experience_level = request.GET.get('experience_level', '')
    graduation_year = request.GET.get('graduation_year', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')

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
    if category_id:
        alumni_list = alumni_list.filter(categories__id=category_id)
    if technology_id:
        alumni_list = alumni_list.filter(technologies__id=technology_id)

    alumni_list = alumni_list.distinct()

    # Mezuniyet yıllarını unique olarak al
    graduation_years = Alumni.objects.values_list('graduation_year', flat=True).distinct().order_by('-graduation_year')

    # Pagination - sadece initial load için
    offset = int(request.GET.get('offset', 0))
    has_more = False
    
    # Filtre parametreleri ile total count kontrolü
    if offset == 0:
        total_count = alumni_list.count()
        has_more = total_count > PAGE_SIZE
        alumni_list = alumni_list[:PAGE_SIZE]
    else:
        alumni_list = alumni_list[offset:offset + PAGE_SIZE]
        has_more = alumni_list.count() == PAGE_SIZE

    return render(request, 'alumni/alumni_list.html', {
        'alumni_list': alumni_list,
        'categories': categories,
        'technologies': technologies,
        'graduation_years': graduation_years,
        'selected_experience_level': experience_level,
        'selected_graduation_year': graduation_year,
        'selected_category': category_id,
        'selected_technology': technology_id,
        'query': query,
        'next_offset': offset + PAGE_SIZE if has_more else 0,
        'has_more': has_more,
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


def alumni_detail_by_id(request, alumni_id):
    """Alumni detail by ID - works for both matched and unmatched alumni"""
    alumni = get_object_or_404(Alumni, id=alumni_id)
    experiences = alumni.work_experiences.all()
    
    if alumni.user and alumni.user.username == request.user.username:
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
        elif action == 'delete_profile':
            profile.delete()
            messages.success(request, 'Mezun profiliniz silindi.')
            return redirect('alumni:alumni_list')
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
            
            category_ids = request.POST.getlist('categories')
            technology_ids = request.POST.getlist('technologies')

            profile.save()
            profile.categories.set(category_ids)
            profile.technologies.set(technology_ids)

            messages.success(request, 'Profiliniz başarıyla güncellendi.')
            return redirect('alumni:alumni_profile')
    
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'alumni/alumni_profile_edit.html', {
        'profile': profile,
        'categories': categories,
        'technologies': technologies,
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
