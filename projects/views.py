from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q
from .models import Respons, Request
from .forms import ProjectForm, ProjectUpdateForm, ProjectCommentForm
from .forms import RequestForm
import json

# Create your views here.

@login_required
def project_list(request):
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    
    projects = Respons.objects.all()
    
    if request.user.profile.user_type == 'teacher':
        projects = projects.filter(advisor=request.user)
    elif request.user.profile.user_type == 'student':
        projects = projects.filter(Q(created_by=request.user) | Q(team=request.user))
    
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category:
        projects = projects.filter(category=category)
    if status:
        projects = projects.filter(status=status)
    
    context = {
    'projects': projects,
    'categories': [],
    'statuses': [],
    }
    return render(request, 'projects/project_list.html', context)


@login_required
def request_list(request):
    # teachers see their own requests, students see all
    if request.user.profile.user_type == 'teacher':
        requests = Request.objects.filter(teacher=request.user)
    else:
        requests = Request.objects.all()
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
    project = get_object_or_404(Respons, id=project_id)
    # access control: if your Respons model has visibility controls implement them here
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
            # create a Respons instead of old Project
            # keep using the same form instance shape for now; form should be updated later
            project = form.save(commit=False)
            project.created_by = request.user
            project.advisor = project.request.teacher  # assign teacher from selected Request
            project.save()
            form.save_m2m()
            messages.success(request, 'Proje başarıyla oluşturuldu.')
            return redirect('projects:project_detail', project_id=project.id)
    else:
        form = ProjectForm()
    
    # prepare mapping of Request.id -> teacher_id for template JS
    requests = Request.objects.all().values('id', 'teacher_id')
    request_teacher_map = {str(r['id']): r['teacher_id'] for r in requests}
    return render(request, 'projects/project_form.html', {'form': form, 'action': 'create', 'request_teacher_map': json.dumps(request_teacher_map)})

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Respons, id=project_id)
    if request.user != project.created_by and request.user != project.advisor:
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
    project = get_object_or_404(Respons, id=project_id)
    if request.user != project.created_by and request.user != project.advisor:
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
    project = get_object_or_404(Respons, id=project_id)
    if request.method == 'POST':
        form = ProjectCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.respons = project
            comment.author = request.user
            comment.save()
            messages.success(request, 'Yorumunuz başarıyla eklendi.')
    return redirect('projects:project_detail', project_id=project.id)
