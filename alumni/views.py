from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from django.http import JsonResponse
from django.template.loader import render_to_string
import logging

from projects.models import ProjectCategory, Technology

from .models import Alumni, WorkExperience
from .forms import AlumniProfileForm, WorkExperienceForm

PAGE_SIZE = 12
logger = logging.getLogger(__name__)


def _safe_offset(request):
    try:
        return max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        return 0


@login_required
def load_more_alumni(request):
    offset = _safe_offset(request)
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
            models.Q(full_name__icontains=query) |
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

    items = render_to_string(
        'alumni/partials/alumni_item.html',
        {'alumni_list': alumni},
        request=request,
    )

    return JsonResponse({
        'items': items,
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
            models.Q(full_name__icontains=query) |
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
    offset = _safe_offset(request)
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

@login_required
def alumni_detail(request, username):
    alumni = get_object_or_404(Alumni, user__username=username)
    experiences = alumni.work_experiences.all()
    if alumni.user_id == request.user.id:
        return redirect('alumni:alumni_profile')
    return render(request, 'alumni/alumni_detail.html', {
        'alumni': alumni,
        'experiences': experiences
    })


@login_required
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
            form = AlumniProfileForm(request.POST, instance=profile)
            if form.is_valid():
                profile = form.save(commit=False)
                profile.user = request.user
                profile.save()
                form.save_m2m()
                messages.success(request, 'Profiliniz başarıyla güncellendi.')
                return redirect('alumni:alumni_profile')
            messages.error(request, 'Profil kaydedilemedi. Lütfen alanları kontrol edin.')
    
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'alumni/alumni_profile_edit.html', {
        'profile': profile,
        'categories': categories,
        'technologies': technologies,
    })

def add_experience(request, profile):
    try:
        if not profile.pk:
            profile.user = request.user
            profile.save()
        form = WorkExperienceForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'success': False, 'error': 'Deneyim bilgilerini ve tarihleri kontrol edin.'}, status=400)
        experience = form.save(commit=False)
        experience.person = profile
        experience.save()
        return JsonResponse({'success': True})
    except Exception:
        logger.exception('İş deneyimi eklenemedi.')
        return JsonResponse({'success': False, 'error': 'Deneyim eklenirken bir hata oluştu.'}, status=500)

def delete_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        experience.delete()
        return JsonResponse({'success': True})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception:
        logger.exception('İş deneyimi silinemedi.')
        return JsonResponse({'success': False, 'error': 'Deneyim silinirken bir hata oluştu.'}, status=500)

def get_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        
        experience_data = {
            'id': experience.id,
            'company': experience.company,
            'position': experience.position,
            'start_date': experience.start_date.isoformat(),
            'end_date': experience.end_date.isoformat() if experience.end_date else None,
            'is_current': experience.is_current,
            'description': experience.description
        }
        
        return JsonResponse({'success': True, 'experience': experience_data})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception:
        logger.exception('İş deneyimi okunamadı.')
        return JsonResponse({'success': False, 'error': 'Deneyim okunurken bir hata oluştu.'}, status=500)

def edit_experience(request, profile):
    try:
        experience_id = request.POST.get('experience_id')
        experience = WorkExperience.objects.get(id=experience_id, person=profile)
        
        form = WorkExperienceForm(request.POST, instance=experience)
        if not form.is_valid():
            return JsonResponse({'success': False, 'error': 'Deneyim bilgilerini ve tarihleri kontrol edin.'}, status=400)
        form.save()
        return JsonResponse({'success': True})
    except WorkExperience.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Deneyim bulunamadı'})
    except Exception:
        logger.exception('İş deneyimi güncellenemedi.')
        return JsonResponse({'success': False, 'error': 'Deneyim güncellenirken bir hata oluştu.'}, status=500)
