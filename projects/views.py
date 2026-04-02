from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from .models import Project, ProjectRequest, ProjectCategory, Technology, ProjectUpdate, ProjectComment
from .forms import ProjectForm, ProjectUpdateForm, ProjectCommentForm
from .forms import RequestForm
from django.template.loader import render_to_string
import json

PAGE_SIZE = 14

def get_student_users():
    return User.objects.filter(Q(profile__user_type='student') | Q(old_profile__user_type='student')).distinct()

# Create your views here.

def project_list(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')
    status = request.GET.get('status', '')
    offset = int(request.GET.get('offset', 0))
    
    projects = Project.objects.prefetch_related('categories', 'technologies').all()
    
    # Check if user is authenticated and get user type
    user = request.user if request.user.is_authenticated else None
    user_type = user.profile.user_type if user and hasattr(user, 'profile') else None
    
    # Privacy Filter: Teachers and Staff can see all projects, others need permission
    if user_type not in ['teacher', 'staff_student']:
        # For non-teachers/staff, show only public and completed projects (hide drafts)
        projects = projects.filter(is_private=False, status='completed')
    # Note: We don't filter by user relationships for non-authenticated users
    
    # Role-based filtering (only for teachers)
    if user_type == 'teacher':
        projects = projects.filter(advisor=user)
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(status=status)
    
    total_count = projects.distinct().count()
    projects = projects.distinct()[offset:offset + PAGE_SIZE]
    has_more = offset + PAGE_SIZE < total_count
    
    context = {
        'projects': projects,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
        'statuses': Project.STATUS_CHOICES,
        'selected_category': category_id,
        'selected_technology': technology_id,
        'selected_status': status,
        'has_more': has_more,
        'next_offset': offset + PAGE_SIZE,
        'total_count': total_count,
        'is_authenticated': request.user.is_authenticated,  # Pass to template
    }
    return render(request, 'projects/project_list.html', context)


def project_load_more(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')
    status = request.GET.get('status', '')
    offset = int(request.GET.get('offset', 0))
    limit = PAGE_SIZE
    
    projects = Project.objects.prefetch_related('categories', 'technologies').all()
    
    # Check if user is authenticated and get user type
    user = request.user if request.user.is_authenticated else None
    user_type = user.profile.user_type if user and hasattr(user, 'profile') else None
    
    # Privacy Filter: Teachers and Staff can see all projects, others need permission
    if user_type not in ['teacher', 'staff_student']:
        # For non-teachers/staff, show only public and completed projects (hide drafts)
        projects = projects.filter(is_private=False, status='completed')
    # Note: We don't filter by user relationships for non-authenticated users
    
    # Role-based filtering (only for teachers)
    if user_type == 'teacher':
        projects = projects.filter(advisor=user)
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(status=status)
    
    total_count = projects.distinct().count()
    projects = projects.distinct()[offset:offset + limit]
    has_more = offset + limit < total_count
    
    html = render_to_string('projects/partials/project_item.html', {'projects': projects})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })


@login_required
def request_list(request):
    # teachers see their own requests, students see all
    if request.user.profile.user_type == 'teacher':
        requests = ProjectRequest.objects.filter(teacher=request.user)
    else:
        requests = ProjectRequest.objects.all()
    return render(request, 'projects/request_list.html', {'requests': requests})


@login_required
def request_create(request):
    if request.method == 'POST':
        form = RequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.teacher = request.user
            req.save()
            form.save_m2m()
            messages.success(request, 'Proje isteği başarıyla oluşturuldu.')
            return redirect('dashboard:requests')
    else:
        form = RequestForm()
    return render(request, 'projects/request_form.html', {
        'form': form,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
    })


@login_required
def request_edit(request, request_id):
    req = get_object_or_404(ProjectRequest, id=request_id)
    if req.teacher != request.user and not request.user.is_staff:
        messages.error(request, 'Bu isteği düzenleme yetkiniz yok.')
        return redirect('dashboard:requests')

    if request.method == 'POST':
        form = RequestForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            messages.success(request, 'Proje isteği başarıyla güncellendi.')
            return redirect('dashboard:requests')
    else:
        form = RequestForm(instance=req)
    return render(request, 'projects/request_form.html', {
        'form': form,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
    })


@login_required
def request_delete(request, request_id):
    req = get_object_or_404(ProjectRequest, id=request_id)
    if req.teacher != request.user and not request.user.is_staff:
        messages.error(request, 'Bu isteği silme yetkiniz yok.')
        return redirect('dashboard:requests')

    if req.projects.exists():
        messages.error(request, 'Bu istekle ilişkili proje olduğu için silinemez.')
        return redirect('dashboard:requests')

    if request.method == 'POST':
        req.delete()
        messages.success(request, 'Proje isteği başarıyla silindi.')
        return redirect('dashboard:requests')

    return redirect('dashboard:requests')


def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    # Check if user is authenticated and get user type
    user = request.user if request.user.is_authenticated else None
    user_type = user.profile.user_type if user and hasattr(user, 'profile') else None
    
    # Block access to draft projects for non-teachers/staff
    if project.status == 'draft' and (not user or user_type not in ['teacher', 'staff_student']):
        messages.error(request, 'Bu proje henüz tamamlanmamış ve görüntülemek için yetkiniz bulunmuyor.')
        return redirect('projects:project_list')
    
    # Access control for private projects
    if project.is_private:
        # Handle anonymous users
        if not user or not user.is_authenticated:
            messages.error(request, 'Bu proje gizlidir ve görüntüleme için giriş yapmanız gerekiyor.')
            return redirect('projects:project_list')
            
        is_team_member = user in project.team.all()
        is_advisor = user == project.advisor
        is_creator = user == project.created_by
        is_staff_or_teacher = hasattr(user, 'profile') and user.profile.user_type in ('staff_student', 'teacher')
        
        if not (is_team_member or is_advisor or is_creator or is_staff_or_teacher):
            messages.error(request, 'Bu proje gizlidir ve size görüntüleme yetkisi verilmedi.')
            return redirect('projects:project_list')
    
    updates = project.updates.all()
    comments = project.comments.all()
    
    # Only show comment form for authenticated users
    if request.user.is_authenticated:
        comment_form = ProjectCommentForm()
    else:
        comment_form = None
    
    context = {
        'project': project,
        'updates': updates,
        'comments': comments,
        'comment_form': comment_form,
    }
    return render(request, 'projects/project_detail.html', context)

@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST, request.FILES)
        if form.is_valid():
            # create a Project instead of old Respons
            # keep using the same form instance shape for now; form should be updated later

            project = form.save(commit=False)
            project.created_by = request.user
            project.advisor = project.project_request.teacher  # assign teacher from selected ProjectRequest
            project.save()
            form.save_m2m()

            messages.success(request, 'Proje başarıyla oluşturuldu.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        # Pre-select the current user in the team field if they are a student
        initial_team = []
        if request.user.profile.user_type == 'student':
            initial_team = [request.user.id]
        initial = {'team': initial_team}
        # Pre-select request if provided via query param
        request_id = request.GET.get('request')
        if request_id:
            try:
                initial['project_request'] = int(request_id)
            except (ValueError, TypeError):
                pass
        form = ProjectForm(initial=initial)

    request_data = {}
    for req in ProjectRequest.objects.all().prefetch_related('categories', 'technologies'):
        teacher_name = f"{req.teacher.first_name} {req.teacher.last_name}".strip() if req.teacher else 'Belirtilmemiş'
        request_data[str(req.id)] = {
            'id': req.teacher_id,
            'name': teacher_name,
            'description': req.description or '',
            'requirements': req.requirements or '',
            'category_ids': list(req.categories.values_list('id', flat=True)),
            'technology_ids': list(req.technologies.values_list('id', flat=True)),
        }
    team_members = get_student_users()
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {
        'form': form,
        'action': 'create',
        'request_data_json': json.dumps(request_data),
        'team_members': team_members,
        'categories': categories,
        'technologies': technologies,
    })

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    # Check if user is creator, advisor, or team member
    is_team_member = request.user in project.team.all()
    if request.user != project.created_by and request.user != project.advisor and not is_team_member:
        messages.error(request, 'Bu projeyi düzenleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        form = ProjectForm(request.POST, request.FILES, instance=project)
        if form.is_valid():
            updated_project = form.save(commit=False)
            if updated_project.project_request:
                updated_project.advisor = updated_project.project_request.teacher
            updated_project.save()
            form.save_m2m()
            messages.success(request, 'Proje başarıyla güncellendi.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm(instance=project)

    request_data = {}
    for req in ProjectRequest.objects.all().prefetch_related('categories', 'technologies'):
        teacher_name = f"{req.teacher.first_name} {req.teacher.last_name}".strip() if req.teacher else 'Belirtilmemiş'
        request_data[str(req.id)] = {
            'id': req.teacher_id,
            'name': teacher_name,
            'description': req.description or '',
            'requirements': req.requirements or '',
            'category_ids': list(req.categories.values_list('id', flat=True)),
            'technology_ids': list(req.technologies.values_list('id', flat=True)),
        }
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {
        'form': form,
        'action': 'update',
        'request_data_json': json.dumps(request_data),
        'team_members': get_student_users(),
        'categories': categories,
        'technologies': technologies,
    })

@login_required
def add_project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    # Check if user is creator, advisor, or team member
    is_team_member = request.user in project.team.all()
    if request.user != project.created_by and request.user != project.advisor and not is_team_member:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Proje güncellemesi ekleme yetkiniz yok.'})
        messages.error(request, 'Proje güncellemesi ekleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        form = ProjectUpdateForm(request.POST)
        if form.is_valid():
            update = form.save(commit=False)
            update.project = project
            update.created_by = request.user
            update.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            
            messages.success(request, 'Proje güncellemesi başarıyla eklendi.')
            return redirect('projects:project_detail', project_id=project.id)
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                if form.errors:
                    for field, field_errors in form.errors.items():
                        errors[field] = field_errors[0] if field_errors else 'Bu alan geçersiz.'
                return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors})
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})
        
        return JsonResponse({'success': False, 'error': 'Bu sayfa artık kullanılmamaktadır. Modal formu kullanın.'})

@login_required
def add_comment(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == 'POST':
        form = ProjectCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.project = project
            comment.author = request.user
            comment.save()
            messages.success(request, 'Yorumunuz başarıyla eklendi.')
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def edit_comment(request, comment_id):
    comment = get_object_or_404(ProjectComment, id=comment_id)
    
    # Check if user can edit this comment
    if request.user != comment.author and not request.user.is_staff:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu yorumu düzenleme yetkiniz yok.'})
        messages.error(request, 'Bu yorumu düzenleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=comment.project.id)
    
    if request.method == 'POST':
        form = ProjectCommentForm(request.POST, instance=comment)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'content': comment.content})
            messages.success(request, 'Yorumunuz başarıyla güncellendi.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                for field, field_errors in form.errors.items():
                    errors[field] = field_errors[0] if field_errors else 'Bu alan geçersiz.'
                return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors})
    else:
        form = ProjectCommentForm(instance=comment)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'content': comment.content})
    
    return redirect('projects:project_detail', project_id=comment.project.id)


@login_required
def delete_comment(request, comment_id):
    comment = get_object_or_404(ProjectComment, id=comment_id)
    project_id = comment.project.id
    
    # Check if user can delete this comment
    if request.user != comment.author and not request.user.is_staff:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu yorumu silme yetkiniz yok.'})
        messages.error(request, 'Bu yorumu silme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project_id)
    
    if request.method == 'POST':
        comment.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, 'Yorumunuz başarıyla silindi.')
    
    return redirect('projects:project_detail', project_id=project_id)