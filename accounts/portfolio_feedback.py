from django.db.models import Q

from projects.models import Project


def build_portfolio_feedback(user):
    """Deterministic completeness feedback; never predicts hiring outcomes."""
    profile = user.profile
    items = []

    def add(title, detail, target_url, severity='medium'):
        items.append({
            'title': title,
            'detail': detail,
            'target_url': target_url,
            'severity': severity,
        })

    if not profile.is_portfolio_public:
        add('Portfolyo görünürlüğü kapalı', 'Dış ziyaretçilerin portfolyonuzu görebilmesi için görünürlüğü açabilirsiniz.',
            '/accounts/portfolio/settings/', 'high')
    if not profile.headline.strip():
        add('Profesyonel başlık eksik', 'Uzmanlık alanınızı tek cümlede anlatan kısa bir başlık ekleyin.',
            '/accounts/portfolio/settings/')
    if len(profile.bio.strip()) < 80:
        add('Hakkımda bölümü kısa', 'İlgi alanlarınızı, hedefinizi ve güçlü yönlerinizi somut biçimde anlatın.',
            '/accounts/portfolio/settings/')
    if not profile.technologies.exists():
        add('Teknoloji listesi eksik', 'Kullandığınız teknolojileri profilinize ekleyin.',
            '/accounts/portfolio/settings/', 'high')

    projects = Project.objects.filter(Q(created_by=user) | Q(team=user)).distinct().select_related(
        'case_study'
    ).prefetch_related('technologies', 'contributions')
    if not projects.exists():
        add('Henüz proje yok', 'En az bir projeyi problem, çözüm ve katkı bilgileriyle portfolyonuza ekleyin.',
            '/projects/create/', 'high')

    for project in projects[:20]:
        manage_url = f'/projects/{project.pk}/showcase/'
        case_study = getattr(project, 'case_study', None)
        if len((project.description or '').strip()) < 80:
            add(f'{project.title}: açıklama geliştirilmeli', 'Problemi, hedef kullanıcıyı ve çözümü daha ayrıntılı açıklayın.', manage_url)
        if not project.technologies.exists():
            add(f'{project.title}: teknolojiler eksik', 'Kullanılan teknolojileri kontrollü teknoloji listesinden seçin.', manage_url)
        if not project.contributions.filter(user=user, contribution_description__gt='').exists():
            add(f'{project.title}: katkınız belirsiz', 'Bu projede hangi işi yaptığınızı doğrulanabilir ve somut biçimde yazın.', manage_url, 'high')
        if not case_study or not case_study.demo_url:
            add(f'{project.title}: canlı demo eksik', 'Uygunsa çalışan bir demo bağlantısı ekleyin.', manage_url, 'low')
        if not hasattr(project, 'repository'):
            add(f'{project.title}: GitHub bağlantısı eksik', 'Herkese açık deponuz varsa güvenli GitHub bağlantısını ekleyin.', manage_url, 'low')
        if not case_study or not case_study.measurable_results.strip():
            add(f'{project.title}: ölçülebilir sonuç eksik', 'Yalnızca gerçek ve doğrulanabilir çıktı veya ölçümleri belirtin.', manage_url)

    total_checks = max(6, len(items) + 6)
    score = max(0, round(100 * (total_checks - len(items)) / total_checks))
    return {
        'score': score,
        'items': items,
        'project_count': projects.count(),
        'disclaimer': 'Bu puan yalnızca içerik tamlığını gösterir; işe alınma veya başarı tahmini değildir.',
    }
