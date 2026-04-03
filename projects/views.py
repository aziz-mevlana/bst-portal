from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from .models import Project, ProjectRequest, ProjectCategory, Technology, ProjectUpdate, ProjectComment, ProjectFeedback
from .forms import ProjectForm, ProjectUpdateForm, ProjectCommentForm, ProjectFeedbackForm
from .forms import RequestForm
from django.template.loader import render_to_string
import json

PAGE_SIZE = 12

def get_student_users():
    return User.objects.filter(Q(profile__user_type='student')).distinct()

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
        if user and user.is_authenticated:
            projects = projects.filter(
                Q(is_private=False, status__in=['in_progress', 'completed']) |
                Q(team=user) |
                Q(created_by=user)
            ).distinct()
        else:
            projects = projects.filter(is_private=False, status__in=['in_progress', 'completed'])
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(status=status)
    
    # First page: minus 1 if "Yeni Proje" card is shown (fills row evenly on 3-col grid)
    show_create_card = request.user.is_authenticated
    page_size = PAGE_SIZE - 1 if (offset == 0 and show_create_card) else PAGE_SIZE
    
    total_count = projects.distinct().count()
    projects = projects.distinct()[offset:offset + page_size]
    has_more = offset + page_size < total_count
    
    context = {
        'projects': projects,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
        'statuses': Project.STATUS_CHOICES,
        'selected_category': category_id,
        'selected_technology': technology_id,
        'selected_status': status,
        'has_more': has_more,
        'next_offset': offset + page_size,
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
        if user and user.is_authenticated:
            projects = projects.filter(
                Q(is_private=False, status__in=['in_progress', 'completed']) |
                Q(team=user) |
                Q(created_by=user)
            ).distinct()
        else:
            projects = projects.filter(is_private=False, status__in=['in_progress', 'completed'])
    
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
    
    # Block access to in_review/approved projects for non-involved users
    if project.status in ['in_review', 'approved']:
        if not user or not user.is_authenticated:
            messages.error(request, 'Bu proje değerlendirme aşamasında ve görüntülemek için giriş yapmanız gerekiyor.')
            return redirect('projects:project_list')
        is_team_member = user in project.team.all()
        is_advisor = user == project.advisor
        is_creator = user == project.created_by
        is_staff_or_teacher = user_type in ('staff_student', 'teacher')
        if not (is_team_member or is_advisor or is_creator or is_staff_or_teacher):
            messages.error(request, 'Bu proje değerlendirme aşamasında ve size görüntüleme yetkisi verilmedi.')
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
    
    # Check if user can see feedback (team members, advisor, staff)
    can_see_feedback = False
    feedback_form = None
    feedback_obj = None
    if request.user.is_authenticated:
        is_team_member = user in project.team.all()
        is_advisor = user == project.advisor
        is_staff_or_teacher = hasattr(user, 'profile') and user.profile.user_type in ('staff_student', 'teacher')
        can_see_feedback = is_team_member or is_advisor or is_staff_or_teacher
        
        try:
            feedback_obj = project.feedback
        except ProjectFeedback.DoesNotExist:
            feedback_obj = None
        
        if is_advisor or is_staff_or_teacher:
            feedback_form = ProjectFeedbackForm(instance=feedback_obj)
    
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
        'feedback_form': feedback_form,
        'feedback_obj': feedback_obj,
        'can_see_feedback': can_see_feedback,
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
            
            # Set status based on supervision type
            if project.project_request.supervision_type == 'supervised':
                project.status = 'in_review'
            else:
                project.status = 'in_progress'
            
            project.save()
            form.save_m2m()

            # Add creator to team
            project.team.add(request.user)

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


@login_required
def approve_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    if request.user != project.advisor and not request.user.is_staff:
        messages.error(request, 'Bu projeyi onaylama yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.status != 'in_review':
        messages.error(request, 'Bu proje onay aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        project.status = 'approved'
        project.save()
        messages.success(request, 'Proje fikri onaylandı.')
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def send_feedback(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    if request.user != project.advisor and not request.user.is_staff:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Geri bildirim gönderme yetkiniz yok.'})
        messages.error(request, 'Geri bildirim gönderme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.status not in ['in_review']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Bu proje değerlendirme aşamasında değil.'})
        messages.error(request, 'Bu proje değerlendirme aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        try:
            feedback = project.feedback
            form = ProjectFeedbackForm(request.POST, instance=feedback)
        except ProjectFeedback.DoesNotExist:
            form = ProjectFeedbackForm(request.POST)
        
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.project = project
            feedback.teacher = request.user
            feedback.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            
            messages.success(request, 'Geri bildirim gönderildi.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                for field, field_errors in form.errors.items():
                    errors[field] = field_errors[0] if field_errors else 'Bu alan geçersiz.'
                return JsonResponse({'success': False, 'error': 'Form doğrulama hatası', 'errors': errors})
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def start_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    is_team_member = request.user in project.team.all()
    if request.user != project.created_by and not is_team_member:
        messages.error(request, 'Bu projeyi başlatma yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.status != 'approved':
        messages.error(request, 'Bu proje henüz fikir onay aşamasında değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        project.status = 'in_progress'
        project.save()
        messages.success(request, 'Proje başlatıldı! Çalışmalara başlayabilirsiniz.')
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def complete_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    is_team_member = request.user in project.team.all()
    is_advisor = request.user == project.advisor
    if request.user != project.created_by and not is_team_member and not is_advisor and not request.user.is_staff:
        messages.error(request, 'Bu projeyi tamamlama yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if project.status != 'in_progress':
        messages.error(request, 'Bu proje devam ediyor durumunda değil.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        project.status = 'completed'
        project.save()
        messages.success(request, 'Proje tamamlandı!')
    
    return redirect('projects:project_detail', project_id=project.id)


@login_required
def get_feedback(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    
    user = request.user
    is_team_member = user in project.team.all()
    is_advisor = user == project.advisor
    is_staff_or_teacher = hasattr(user, 'profile') and user.profile.user_type in ('staff_student', 'teacher')
    
    if not (is_team_member or is_advisor or is_staff_or_teacher):
        return JsonResponse({'success': False, 'error': 'Geri bildirimi görüntüleme yetkiniz yok.'})
    
    try:
        feedback = project.feedback
        return JsonResponse({
            'success': True,
            'content': feedback.content,
            'teacher_name': feedback.teacher.get_full_name(),
            'teacher_id': feedback.teacher.id,
            'created_at': feedback.created_at.strftime('%d.%m.%Y %H:%M'),
            'updated_at': feedback.updated_at.strftime('%d.%m.%Y %H:%M'),
        })
    except ProjectFeedback.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Henüz geri bildirim yok.'})
    
    if request.method == 'POST':
        comment.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, 'Yorumunuz başarıyla silindi.')
    
    return redirect('projects:project_detail', project_id=project_id)


@login_required
def change_project_status(request, project_id):
    import json
    project = get_object_or_404(Project, id=project_id)
    
    user = request.user
    is_team_member = user in project.team.all()
    is_advisor = user == project.advisor
    is_staff_or_teacher = hasattr(user, 'profile') and user.profile.user_type in ('staff_student', 'teacher')
    
    if not (is_advisor or is_staff_or_teacher or is_team_member or user.is_staff):
        return JsonResponse({'success': False, 'error': 'Durum değiştirme yetkiniz yok.'})
    
    if request.method == 'POST':
        data = json.loads(request.body)
        new_status = data.get('status')
        
        # Valid transitions
        transitions = {
            'in_review': ['approved', 'in_progress', 'completed'],
            'approved': ['in_review', 'in_progress', 'completed'],
            'in_progress': ['completed'],
            'completed': ['in_progress'],
        }
        
        current = project.status
        allowed = transitions.get(current, [])
        
        if new_status not in allowed:
            return JsonResponse({'success': False, 'error': f"'{project.get_status_display()}' durumundan geçiş yapılamaz."})
        
        project.status = new_status
        project.save()
        
        return JsonResponse({
            'success': True,
            'new_status': new_status,
            'new_status_display': project.get_status_display(),
        })
    
    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})