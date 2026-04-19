from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Count, Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from projects.models import Project, ProjectRequest, ProjectCategory, Technology
from accounts.models import Profile
from alumni.models import Alumni
from django.contrib.auth.models import User
import json


def is_teacher_or_staff(user):
    """Check if user is teacher or staff student"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type in ['teacher', 'staff_student']


def is_student(user):
    """Check if user is a student"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type == 'student'


def is_alumni(user):
    """Check if user is an alumni"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type == 'alumni'


def is_admin(user):
    """Check if user is admin (staff student) or teacher"""
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return user.profile.user_type in ['staff_student', 'teacher']


DASHBOARD_PAGE_SIZE = 12


def dashboard_home(request):
    """Main dashboard that routes to role-specific home page"""
    user = request.user

    if not user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    if not hasattr(user, 'profile'):
        return render(request, 'dashboard/access_denied.html')

    user_type = user.profile.user_type

    if user_type in ['teacher', 'staff_student']:
        return teacher_dashboard_home(request)
    elif user_type == 'student':
        return student_dashboard_home(request)
    elif user_type == 'alumni':
        return alumni_dashboard_home(request)
    else:
        return render(request, 'dashboard/access_denied.html')


def student_dashboard_home(request):
    """Student dashboard home"""
    if not is_student(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user
    student_class = user.profile.class_level if hasattr(user.profile, 'class_level') else None

    my_projects = Project.objects.filter(team=user).select_related('advisor', 'project_request').prefetch_related('team', 'categories', 'technologies')

    available_requests = ProjectRequest.objects.filter(
        status='open'
    ).select_related('teacher', 'teacher__profile')[:5]

    context = {
        'user_type': 'student',
        'student_class': student_class,
        'my_projects': my_projects,
        'available_requests': available_requests,
    }
    return render(request, 'dashboard/home_student.html', context)


def student_my_projects(request):
    """Student's own projects list"""
    if not is_student(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user
    my_projects = Project.objects.filter(team=user).select_related('advisor', 'project_request').prefetch_related('team', 'categories', 'technologies')

    return render(request, 'dashboard/student_projects.html', {
        'projects': my_projects,
    })


def alumni_projects(request):
    """Redirect alumni to projects list"""
    from django.shortcuts import redirect
    if not is_alumni(request.user):
        return render(request, 'dashboard/access_denied.html')
    return redirect('dashboard:projects')


def alumni_dashboard_home(request):
    """Alumni dashboard home"""
    if not is_alumni(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user

    try:
        alumni = Alumni.objects.get(user=user)
    except Alumni.DoesNotExist:
        alumni = None

    context = {
        'user_type': 'alumni',
        'alumni': alumni,
    }
    return render(request, 'dashboard/home_alumni.html', context)


def dashboard_news(request):
    """Manage AI fetched news"""
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')

    from news.models import Article, NewsKeyword

    pending_news = Article.objects.filter(is_approved=False).order_by('-date')
    approved_news = Article.objects.filter(is_approved=True).order_by('-date')[:20]
    keywords = NewsKeyword.objects.all()

    context = {
        'pending_news': pending_news,
        'approved_news': approved_news,
        'keywords': keywords,
    }
    return render(request, 'dashboard/news_list.html', context)


@login_required
def approve_news(request):
    """Approve a news article"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        news_id = data.get('news_id')

        from news.models import Article
        try:
            article = Article.objects.get(id=news_id)
            article.is_approved = True
            article.save()
            return JsonResponse({'success': True})
        except Article.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Haber bulunamadı.'})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
def reject_news(request):
    """Reject/delete a news article"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        news_id = data.get('news_id')

        from news.models import Article
        try:
            article = Article.objects.get(id=news_id)
            article.delete()
            return JsonResponse({'success': True})
        except Article.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Haber bulunamadı.'})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
def delete_news(request):
    """Delete a news article"""
    return reject_news(request)


@login_required
def approve_all_news(request):
    """Approve all pending news"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    from news.models import Article
    count = Article.objects.filter(is_approved=False).update(is_approved=True)

    return JsonResponse({'success': True, 'count': count})


@login_required
def news_keywords(request):
    """Add or update news keywords"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        keyword = data.get('keyword', '').strip()

        if not keyword:
            return JsonResponse({'success': False, 'error': 'Anahtar kelime gerekli.'})

        from news.models import NewsKeyword
        NewsKeyword.objects.get_or_create(keyword=keyword)
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
def delete_keyword(request):
    """Delete a news keyword"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        keyword_id = data.get('keyword_id')

        from news.models import NewsKeyword
        NewsKeyword.objects.get(id=keyword_id).delete()
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


@login_required
def fetch_news_command(request):
    """Trigger news fetch command"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    import subprocess
    result = subprocess.run(
        ['python3', 'manage.py', 'fetch_news'],
        capture_output=True,
        text=True,
        cwd='/Users/azizalim/Projects/bst-portal'
    )

    return JsonResponse({
        'success': result.returncode == 0,
        'output': result.stdout + result.stderr
    })


def teacher_dashboard_home(request):
    """Teacher/Admin dashboard home"""
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')

    user = request.user
    user_type = user.profile.user_type

    total_alumni = Alumni.objects.count()

    advised_projects = Project.objects.filter(advisor=user)
    total_projects = advised_projects.count()

    total_students = User.objects.filter(
        projects__in=advised_projects,
        profile__user_type='student'
    ).distinct().count()

    pending_approvals = Project.objects.filter(
        advisor=user, status='in_review'
    ).count()

    context = {
        'total_alumni': total_alumni,
        'total_projects': total_projects,
        'total_students': total_students,
        'pending_approvals': pending_approvals,
        'user_type': user_type,
    }
    return render(request, 'dashboard/home_teacher.html', context)


def dashboard_skills(request):
    """Manage categories and technologies"""
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    if request.method == 'POST':
        data = request.POST
        item_type = data.get('type')
        item_id = data.get('id')
        name = data.get('name', '').strip()
        color = data.get('color', '#3B82F6')
        
        if item_type == 'category':
            if item_id:
                cat = ProjectCategory.objects.get(id=item_id)
                cat.name = name
                cat.color = color
                cat.save()
            else:
                ProjectCategory.objects.create(name=name, color=color)
        
        elif item_type == 'technology':
            if item_id:
                tech = Technology.objects.get(id=item_id)
                tech.name = name
                tech.color = color
                tech.save()
            else:
                Technology.objects.create(name=name, color=color)
        
        return JsonResponse({'success': True})
    
    categories = ProjectCategory.objects.all()
    technologies = Technology.objects.all()
    
    context = {
        'categories': categories,
        'technologies': technologies,
    }
    return render(request, 'dashboard/skills.html', context)


@login_required
def delete_skill(request):
    """Delete category or technology"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        item_type = data.get('type')
        item_id = data.get('id')
        
        if item_type == 'category':
            ProjectCategory.objects.get(id=item_id).delete()
        elif item_type == 'technology':
            Technology.objects.get(id=item_id).delete()
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})


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
    
    if status_filter:
        requests = requests.filter(status=status_filter)
    
    context = {
        'requests': requests,
        'query': query,
        'status_filter': status_filter,
    }
    return render(request, 'dashboard/requests.html', context)


def dashboard_students(request):
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    query = request.GET.get('q', '')
    class_level = request.GET.get('class_level', '')
    
    # Tüm öğrencileri al
    students = User.objects.filter(
        Q(profile__user_type='student')
    ).select_related('profile').distinct()
    
    if query:
        students = students.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(username__icontains=query)
        )
    
    if class_level:
        students = students.filter(
            Q(profile__class_level=class_level)
        )
    
    total_count = students.count()
    page_size = DASHBOARD_PAGE_SIZE
    students_page = students[:page_size]
    has_more = total_count > page_size
    
    context = {
        'students': students_page,
        'query': query,
        'class_level': class_level,
        'class_choices': Profile.CLASS_CHOICES,
        'has_more': has_more,
        'next_offset': page_size,
        'total_count': total_count,
    }
    return render(request, 'dashboard/students.html', context)


def dashboard_students_load_more(request):
    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    class_level = request.GET.get('class_level', '')
    
    students = User.objects.filter(
        Q(profile__user_type='student')
    ).select_related('profile').distinct()
    
    if query:
        students = students.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(username__icontains=query)
        )
    
    if class_level:
        students = students.filter(
            Q(profile__class_level=class_level)
        )
    
    total_count = students.count()
    students_page = students[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count
    
    html = render_to_string('dashboard/partials/student_row.html', {'students': students_page})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


def dashboard_projects(request):
    # Check if user is authenticated and is teacher/staff
    user = request.user if request.user.is_authenticated else None
    is_teacher_or_staff = False
    if user and hasattr(user, 'profile'):
        is_teacher_or_staff = user.profile.user_type in ['teacher', 'staff_student']

    # User type for template
    user_type = user.profile.user_type if user and hasattr(user, 'profile') else None

    # Get filter parameters
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    request_id = request.GET.get('project_request', '')
    
    # Base query: if user is teacher/staff, show all projects (except draft)
    # If alumni, show all except draft
    # If student, show only completed
    if is_teacher_or_staff:
        projects = Project.objects.all().prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor', 'created_by')
    elif is_alumni(user):
        projects = Project.objects.exclude(status='draft').prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor')
    else:
        projects = Project.objects.filter(status='completed').prefetch_related('team', 'categories', 'technologies', 'project_request')
    
    # Apply filters
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    
    if status:
        projects = projects.filter(status=status)
        if status == 'draft' and not is_teacher_or_staff:
            projects = Project.objects.none()
    
    if request_id:
        projects = projects.filter(project_request_id=request_id)
    
    total_count = projects.count()
    projects = projects[:DASHBOARD_PAGE_SIZE]
    has_more = total_count > DASHBOARD_PAGE_SIZE
    
    # Get teacher requests for the filter dropdown (only for teachers)
    teacher_requests = ProjectRequest.objects.filter(teacher=user) if is_teacher_or_staff else ProjectRequest.objects.none()
    
    context = {
        'projects': projects,
        'query': query,
        'selected_status': status,
        'statuses': Project.STATUS_CHOICES,
        'teacher_requests': teacher_requests,
        'selected_request': request_id,
        'is_teacher_or_staff': is_teacher_or_staff,
        'user_type': user_type,
        'has_more': has_more,
        'next_offset': DASHBOARD_PAGE_SIZE,
    }
    return render(request, 'dashboard/projects.html', context)


def dashboard_projects_load_more(request):
    user = request.user if request.user.is_authenticated else None
    is_teacher_or_staff = False
    if user and hasattr(user, 'profile'):
        is_teacher_or_staff = user.profile.user_type in ['teacher', 'staff_student']
    
    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    request_id = request.GET.get('project_request', '')
    
    if is_teacher_or_staff:
        projects = Project.objects.all().prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor', 'created_by')
    elif hasattr(user, 'profile') and user.profile.user_type == 'alumni':
        projects = Project.objects.exclude(status='draft').prefetch_related('team', 'categories', 'technologies', 'project_request', 'advisor')
    else:
        projects = Project.objects.filter(status='completed').prefetch_related('team', 'categories', 'technologies', 'project_request')

    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if status:
        projects = projects.filter(status=status)
        if status == 'draft' and not is_teacher_or_staff:
            projects = Project.objects.none()
    if request_id:
        projects = projects.filter(project_request_id=request_id)

    total_count = projects.count()
    projects = projects[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count
    
    html = render_to_string('dashboard/partials/project_card.html', {'projects': projects})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


def dashboard_alumni(request):
    if not is_teacher_or_staff(request.user):
        return render(request, 'dashboard/access_denied.html')

    query = request.GET.get('q', '')
    experience = request.GET.get('experience', '')
    mentoring = request.GET.get('mentoring', '')
    matched = request.GET.get('matched', '')
    category = request.GET.get('category', '')
    technology = request.GET.get('technology', '')

    alumni = Alumni.objects.select_related('user', 'user__profile').prefetch_related('technologies', 'categories')

    if query:
        alumni = alumni.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(full_name__icontains=query) |
            Q(company__icontains=query) |
            Q(current_position__icontains=query)
        )

    if experience:
        alumni = alumni.filter(experience_level=experience)

    if mentoring == '1':
        alumni = alumni.filter(is_available_for_mentoring=True)

    if matched == 'yes':
        alumni = alumni.filter(user__isnull=False)
    elif matched == 'no':
        alumni = alumni.filter(user__isnull=True)

    if category:
        alumni = alumni.filter(categories__id=category)

    if technology:
        alumni = alumni.filter(technologies__id=technology)

    total_count = alumni.count()
    alumni_list = alumni[:DASHBOARD_PAGE_SIZE]
    has_more = total_count > DASHBOARD_PAGE_SIZE
    next_offset = DASHBOARD_PAGE_SIZE if has_more else 0

    context = {
        'alumni_list': alumni_list,
        'total_count': total_count,
        'has_more': has_more,
        'next_offset': next_offset,
        'query': query,
        'selected_experience': experience,
        'selected_mentoring': mentoring,
        'selected_matched': matched,
        'selected_category': category,
        'selected_technology': technology,
        'experience_choices': Alumni.EXPERIENCE_LEVEL_CHOICES,
        'categories': ProjectCategory.objects.all(),
        'technologies': Technology.objects.all(),
    }
    return render(request, 'dashboard/alumni.html', context)


def dashboard_alumni_load_more(request):
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    offset = int(request.GET.get('offset', 0))
    query = request.GET.get('q', '')
    experience = request.GET.get('experience', '')
    mentoring = request.GET.get('mentoring', '')
    matched = request.GET.get('matched', '')
    category = request.GET.get('category', '')
    technology = request.GET.get('technology', '')

    alumni = Alumni.objects.select_related('user', 'user__profile').prefetch_related('technologies', 'categories')

    if query:
        alumni = alumni.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(full_name__icontains=query) |
            Q(company__icontains=query) |
            Q(current_position__icontains=query)
        )

    if experience:
        alumni = alumni.filter(experience_level=experience)

    if mentoring == '1':
        alumni = alumni.filter(is_available_for_mentoring=True)

    if matched == 'yes':
        alumni = alumni.filter(user__isnull=False)
    elif matched == 'no':
        alumni = alumni.filter(user__isnull=True)

    if category:
        alumni = alumni.filter(categories__id=category)

    if technology:
        alumni = alumni.filter(technologies__id=technology)

    total_count = alumni.count()
    alumni_page = alumni[offset:offset + DASHBOARD_PAGE_SIZE]
    has_more = offset + DASHBOARD_PAGE_SIZE < total_count

    html = render_to_string('dashboard/partials/alumni_row.html', {'alumni_list': alumni_page})

    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + DASHBOARD_PAGE_SIZE,
    })


@login_required
def match_alumni(request):
    """Mezun kaydını bir kullanıcı profiliyle eşleştir"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        alumni_id = data.get('alumni_id')
        user_id = data.get('user_id')

        try:
            alumni = Alumni.objects.get(id=alumni_id)
        except Alumni.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Mezun kaydı bulunamadı.'})

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Kullanıcı bulunamadı.'})

        # Bu kullanıcı zaten bir mezun kaydına bağlı mı kontrol et
        if Alumni.objects.filter(user=user).exclude(id=alumni_id).exists():
            return JsonResponse({'success': False, 'error': 'Bu kullanıcı zaten başka bir mezun kaydına bağlı.'})

        alumni.user = user
        alumni.save()

        return JsonResponse({
            'success': True,
            'user_name': user.get_full_name(),
            'user_email': user.email,
        })

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
def unmatch_alumni(request):
    """Mezun kaydından kullanıcı bağlantısını kaldır"""
    import json
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        alumni_id = data.get('alumni_id')

        try:
            alumni = Alumni.objects.get(id=alumni_id)
        except Alumni.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Mezun kaydı bulunamadı.'})

        alumni.user = None
        alumni.save()

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
def search_users(request):
    """Eşleştirme için kullanıcı arama"""
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'results': []})

    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})

    users = User.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(email__icontains=query)
    ).select_related('profile')[:20]

    results = []
    for user in users:
        user_type = ''
        if hasattr(user, 'profile'):
            user_type = user.profile.get_user_type_display()
        
        already_matched = Alumni.objects.filter(user=user).exists()
        
        results.append({
            'id': user.id,
            'name': user.get_full_name() or user.username,
            'email': user.email,
            'user_type': user_type,
            'already_matched': already_matched,
        })

    return JsonResponse({'results': results})


@login_required
def update_student_class(request):
    """Öğrenci sınıfını güncelle"""
    import json
    if not is_teacher_or_staff(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        student_id = data.get('student_id')
        class_level = data.get('class_level')

        try:
            user = User.objects.get(id=student_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Kullanıcı bulunamadı.'})

        if not hasattr(user, 'profile'):
            return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})

        user.profile.class_level = class_level
        user.profile.save()

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})


@login_required
def dashboard_academics(request):
    """List all academics (teachers)"""
    if not is_admin(request.user):
        return render(request, 'dashboard/access_denied.html')
    
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    
    # Get all teachers with their profiles
    academics = User.objects.filter(
        profile__user_type='teacher'
    ).select_related('profile')
    
    if query:
        academics = academics.filter(
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(email__icontains=query)
        )
    
    if status == 'pending':
        academics = academics.filter(is_active=False)
    elif status == 'active':
        academics = academics.filter(is_active=True)
    
    academics = academics.order_by('-date_joined')
    
    pending_count = academics.filter(is_active=False).count()
    active_count = academics.filter(is_active=True).count()
    
    return render(request, 'dashboard/academics.html', {
        'academics': academics,
        'pending_count': pending_count,
        'active_count': active_count,
        'total_count': academics.count(),
        'query': query,
        'selected_status': status,
    })


@login_required
def approve_academic(request):
    """Approve a pending academic"""
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Yetkiniz yok.'})
    
    if request.method == 'POST':
        data = json.loads(request.body)
        user_id = data.get('user_id')
        
        try:
            user = User.objects.get(id=user_id, profile__user_type='teacher')
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Akademisyen bulunamadı.'})
        
        # Öğretim üyeleri başka öğretim üyelerini onaylayabilir (kendileri hariç)
        if request.user.profile.user_type == 'teacher' and user.id == request.user.id:
            return JsonResponse({'success': False, 'error': 'Kendi hesabınızı onaylayamazsınız.'})
        
        user.is_active = True
        user.save()
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Sadece POST istekleri kabul edilir.'})