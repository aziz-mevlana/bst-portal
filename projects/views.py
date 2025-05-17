from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Project, ProjectUpdate, ProjectComment

# Create your views here.

@login_required
def project_list(request):
    if request.user.profile.user_type == 'teacher':
        projects = Project.objects.filter(supervisor=request.user)
    else:
        projects = Project.objects.filter(student=request.user)
    return render(request, 'projects/project_list.html', {'projects': projects})

@login_required
def project_detail(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.student and request.user != project.supervisor:
        messages.error(request, 'Bu projeye erişim izniniz yok.')
        return redirect('projects:project_list')
    
    updates = project.updates.all()
    comments = project.comments.all()
    return render(request, 'projects/project_detail.html', {
        'project': project,
        'updates': updates,
        'comments': comments
    })

@login_required
def project_upload(request):
    if request.method == 'POST':
        # Proje yükleme işlemleri burada yapılacak
        pass
    return render(request, 'projects/project_upload.html')

@login_required
def project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.user != project.student:
        messages.error(request, 'Sadece proje sahibi güncelleme yapabilir.')
        return redirect('projects:project_detail', project_id=project.id)
    
    if request.method == 'POST':
        # Proje güncelleme işlemleri burada yapılacak
        pass
    return render(request, 'projects/project_update.html', {'project': project})

@login_required
def add_comment(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            ProjectComment.objects.create(
                project=project,
                content=content,
                author=request.user
            )
            messages.success(request, 'Yorumunuz başarıyla eklendi.')
    return redirect('projects:project_detail', project_id=project.id)
