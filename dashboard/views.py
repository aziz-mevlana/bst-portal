from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from projects.models import Project, ProjectRequest
from accounts.models import Profile
from django.contrib.auth.models import User


def is_teacher_or_staff(user):
    """Check if user is teacher or staff student"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type in ['teacher', 'staff_student']


def dashboard_home(request):
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    user = request.user
    user_type = user.profile.user_type
    
    # İstatistiksel Özet
    total_requests = ProjectRequest.objects.filter(teacher=user).count()
    
    # Danışmanı olduğu projeler
    advised_projects = Project.objects.filter(advisor=user)
    total_projects = advised_projects.count()
    
    # Toplam Öğrenci Sayısı (Danışmanı olduğu projelerdeki takım üyeleri)
    total_students = User.objects.filter(
        projects__in=advised_projects,
        profile__user_type='student'
    ).distinct().count()
    
    # Aktif Proje İstekleri (Proje üretilmemiş olanlar)
    active_requests = ProjectRequest.objects.filter(
        teacher=user
    ).exclude(
        projects__isnull=False
    ).count()
    
    context = {
        'total_requests': total_requests,
        'total_projects': total_projects,
        'total_students': total_students,
        'active_requests': active_requests,
        'user_type': user_type,
    }
    return render(request, 'dashboard/home.html', context)


def dashboard_requests(request):
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    user = request.user
    
    # Filtreleme
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    requests = ProjectRequest.objects.filter(teacher=user).prefetch_related('projects')
    
    if query:
        requests = requests.filter(title__icontains=query)
    
    if status_filter == 'active':
        requests = requests.filter(projects__isnull=True)
    elif status_filter == 'completed':
        requests = requests.filter(projects__isnull=False)
    
    context = {
        'requests': requests,
        'query': query,
        'status_filter': status_filter,
    }
    return render(request, 'dashboard/requests.html', context)


def dashboard_students(request):
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    user = request.user
    
    # Filtreleme
    query = request.GET.get('q', '')
    project_id = request.GET.get('project', '')
    
    # Danışmanı olduğu projeler
    advised_projects = Project.objects.filter(advisor=user)
    
    if project_id:
        advised_projects = advised_projects.filter(id=project_id)
    
    # Bu projelerdeki öğrencileri topla
    # ManyToMany ilişki üzerinden profile filtreleme yaparken dikkatli olmak gerekir
    # Direkt User olarak alıp profile göre filtreleyelim
    students_data = []
    # Projeleri ve öğrencileri eşleştir
    for project in advised_projects:
        # Takım üyelerini al
        team_members = project.team.all()
        for student in team_members:
            # Öğrenci profili var mı ve tipi student mı kontrol et
            if hasattr(student, 'profile') and student.profile.user_type == 'student':
                students_data.append({
                    'student': student,
                    'project': project,
                })
    
    # Arama filtresi
    if query:
        query_lower = query.lower()
        students_data = [
            item for item in students_data
            if query_lower in item['student'].get_full_name().lower() or
               query_lower in item['student'].username.lower() or
               query_lower in item['project'].title.lower()
        ]
    
    # Benzersiz öğrencileri göstermek için (aynı öğrenci birden fazla projede olabilir)
    # Şimdilik tüm kayıtları gösteriyoruz, ama duplicate check yapılabilir
    # duplicate_students = set()
    # unique_data = []
    # for item in students_data:
    #     if item['student'].id not in duplicate_students:
    #         unique_data.append(item)
    #         duplicate_students.add(item['student'].id)
    # students_data = unique_data
    
    context = {
        'students_data': students_data,
        'projects': advised_projects,
        'query': query,
        'selected_project': project_id,
    }
    return render(request, 'dashboard/students.html', context)


def dashboard_projects(request):
    # Check if user is authenticated and is teacher/staff
    user = request.user if request.user.is_authenticated else None
    is_teacher_or_staff = False
    if user and hasattr(user, 'profile'):
        is_teacher_or_staff = user.profile.user_type in ['teacher', 'staff_student']
    
    # Get filter parameters
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    request_id = request.GET.get('project_request', '')
    
    # Base query: if user is teacher/staff, show their advised projects
    # Otherwise, show only completed projects
    if is_teacher_or_staff:
        projects = Project.objects.filter(advisor=user).prefetch_related('team', 'categories', 'technologies', 'project_request')
    else:
        # Show only completed projects to non-authenticated or non-teacher users
        projects = Project.objects.filter(status='completed').prefetch_related('team', 'categories', 'technologies', 'project_request')
    
    # Apply filters
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    
    if status:
        projects = projects.filter(status=status)
        # If someone is trying to filter by draft status but is not authorized, 
        # we should still respect the filter but they'll see nothing if not advisor
        if status == 'draft' and not is_teacher_or_staff:
            projects = Project.objects.none()  # Return empty queryset
    
    if request_id:
        projects = projects.filter(project_request_id=request_id)
    
    # Get teacher requests for the filter dropdown (only for teachers)
    teacher_requests = ProjectRequest.objects.filter(teacher=user) if is_teacher_or_staff else ProjectRequest.objects.none()
    
    context = {
        'projects': projects,
        'query': query,
        'selected_status': status,
        'statuses': Project.STATUS_CHOICES,
        'teacher_requests': teacher_requests,
        'selected_request': request_id,
        'is_teacher_or_staff': is_teacher_or_staff,  # Pass to template for conditional UI
    }
    return render(request, 'dashboard/projects.html', context)