from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q
from .models import Project, ProjectUpdate, ProjectComment
from .forms import ProjectForm, ProjectUpdateForm, ProjectCommentForm

# Create your views here.

@login_required
def project_list(request):
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    
    projects = Project.objects.all()
    
    if request.user.profile.user_type == 'teacher':
        projects = projects.filter(supervisor=request.user)
    elif request.user.profile.user_type == 'student':
        projects = projects.filter(Q(student=request.user) | Q(team_members=request.user))
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category:
        projects = projects.filter(category=category)
    if status:
        projects = projects.filter(status=status)
    
    context = {
        'projects': projects,
        'categories': Project.CATEGORY_CHOICES,
        'statuses': Project.STATUS_CHOICES,
    }
    return render(request, 'projects/project_list.html', context)

@login_required
def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not project.is_public and request.user != project.student and request.user != project.supervisor and request.user not in project.team_members.all():
        messages.error(request, 'Bu projeye erişim izniniz yok.')
        return redirect('projects:project_list')
    
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
            project = form.save(commit=False)
            project.student = request.user
            project.save()
            form.save_m2m()  # Takım üyelerini kaydet
            messages.success(request, 'Proje başarıyla oluşturuldu.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm()
    
    return render(request, 'projects/project_form.html', {'form': form, 'action': 'create'})

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.student and request.user != project.supervisor:
        messages.error(request, 'Bu projeyi düzenleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        form = ProjectForm(request.POST, request.FILES, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, 'Proje başarıyla güncellendi.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm(instance=project)
    
    return render(request, 'projects/project_form.html', {'form': form, 'action': 'update'})

@login_required
def add_project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.student and request.user != project.supervisor:
        messages.error(request, 'Proje güncellemesi ekleme yetkiniz yok.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        form = ProjectUpdateForm(request.POST)
        if form.is_valid():
            update = form.save(commit=False)
            update.project = project
            update.created_by = request.user
            update.save()
            messages.success(request, 'Proje güncellemesi başarıyla eklendi.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectUpdateForm()
    
    return render(request, 'projects/project_update_form.html', {'form': form})

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
