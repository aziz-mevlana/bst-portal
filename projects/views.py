from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from .models import Project, ProjectRequest, ProjectCategory, Technology, ProjectUpdate, ProjectComment
from .forms import ProjectForm, ProjectUpdateForm, ProjectCommentForm
from .forms import RequestForm
import json

def get_student_users():
    return User.objects.filter(Q(profile__user_type='student') | Q(old_profile__user_type='student')).distinct()

# Create your views here.

@login_required
def project_list(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    technology_id = request.GET.get('technology', '')
    status = request.GET.get('status', '')
    
    projects = Project.objects.prefetch_related('categories', 'technologies').all()
    
    if request.user.profile.user_type == 'teacher':
        projects = projects.filter(advisor=request.user)
    elif request.user.profile.user_type == 'student':
        projects = projects.filter(Q(created_by=request.user) | Q(team=request.user))
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category_id:
        projects = projects.filter(categories__id=category_id)
    if technology_id:
        projects = projects.filter(technologies__id=technology_id)
    if status:
        projects = projects.filter(status=status)
    
    context = {
        'projects': projects.distinct(),
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
        'statuses': Project.STATUS_CHOICES,
        'selected_category': category_id,
        'selected_technology': technology_id,
        'selected_status': status,
    }
    return render(request, 'projects/project_list.html', context)


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
            messages.success(request, 'Request oluşturuldu.')
            return redirect('projects:request_list')
    else:
        form = RequestForm()
    return render(request, 'projects/request_form.html', {'form': form})

@login_required
def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    # access control: if your Project model has visibility controls implement them here
    updates = project.updates.all()
    comments = project.comments.all()
    comment_form = ProjectCommentForm()
    
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
        form = ProjectForm()

    requests = ProjectRequest.objects.all().values('id', 'teacher_id', 'teacher__first_name', 'teacher__last_name')
    request_teacher_map = {str(r['id']): {'id': r['teacher_id'], 'name': f"{r['teacher__first_name']} {r['teacher__last_name']}".strip() or 'Belirtilmemiş'} for r in requests}
    team_members = get_student_users()
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {'form': form, 'action': 'create', 'request_teacher_map': json.dumps(request_teacher_map), 'team_members': team_members, 'categories': categories, 'technologies': technologies})

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.created_by and request.user != project.advisor:
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
    
    requests = ProjectRequest.objects.all().values('id', 'teacher_id', 'teacher__first_name', 'teacher__last_name')
    request_teacher_map = {str(r['id']): {'id': r['teacher_id'], 'name': f"{r['teacher__first_name']} {r['teacher__last_name']}".strip() or 'Belirtilmemiş'} for r in requests}
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    return render(request, 'projects/project_form.html', {'form': form, 'action': 'update', 'request_teacher_map': json.dumps(request_teacher_map), 'team_members': get_student_users(), 'categories': categories, 'technologies': technologies})

@login_required
def add_project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.created_by and request.user != project.advisor:
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