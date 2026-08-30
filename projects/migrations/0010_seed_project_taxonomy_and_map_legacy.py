from django.db import migrations


PROJECT_TYPES = [
    {
        'code': 'INDEPENDENT',
        'name': 'Bağımsız Öğrenci Projesi',
        'slug': 'bagimsiz-ogrenci-projesi',
        'requires_approval': False,
    },
    {
        'code': 'COURSE',
        'name': 'Ders Projesi',
        'slug': 'ders-projesi',
        'requires_course': True,
        'requires_approval': True,
    },
    {
        'code': 'CAPSTONE',
        'name': 'Bitirme Projesi',
        'slug': 'bitirme-projesi',
        'requires_advisor': True,
        'requires_approval': True,
    },
    {
        'code': 'RESEARCH',
        'name': 'Araştırma Projesi',
        'slug': 'arastirma-projesi',
        'requires_advisor': True,
        'requires_approval': True,
    },
    {
        'code': 'COMMUNITY',
        'name': 'Topluluk/Bölüm Projesi',
        'slug': 'topluluk-bolum-projesi',
        'requires_organization': True,
    },
    {
        'code': 'STARTUP_PRODUCT',
        'name': 'Girişim/Ürün Geliştirme Projesi',
        'slug': 'girisim-urun-gelistirme-projesi',
    },
    {
        'code': 'INTERNSHIP',
        'name': 'Staj/İşyeri Projesi',
        'slug': 'staj-isyeri-projesi',
        'requires_organization': True,
        'requires_approval': True,
    },
]

PROGRAMS = [
    ('TÜBİTAK 2209-A', 'tubitak-2209-a', 'support', 10),
    ('TÜBİTAK 2209-B', 'tubitak-2209-b', 'support', 20),
    ('TEKNOFEST', 'teknofest', 'competition', 30),
]


def seed_and_map(apps, schema_editor):
    ProjectType = apps.get_model('projects', 'ProjectType')
    ProjectProgram = apps.get_model('projects', 'ProjectProgram')
    ProjectRequest = apps.get_model('projects', 'ProjectRequest')
    Project = apps.get_model('projects', 'Project')

    project_types = {}
    for sort_order, item in enumerate(PROJECT_TYPES, start=1):
        defaults = dict(item)
        code = defaults.pop('code')
        defaults['sort_order'] = sort_order * 10
        project_type, _ = ProjectType.objects.update_or_create(code=code, defaults=defaults)
        project_types[code] = project_type

    for name, slug, program_type, sort_order in PROGRAMS:
        ProjectProgram.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name,
                'program_type': program_type,
                'sort_order': sort_order,
                'is_active': True,
            },
        )

    for project_request in ProjectRequest.objects.all().iterator():
        request_type = project_types['COURSE'] if project_request.course else project_types['INDEPENDENT']
        old_status = project_request.status
        first_project = project_request.projects.order_by('pk').first()
        if first_project:
            new_status = 'student_selected'
        elif old_status == 'active':
            new_status = 'open'
        elif old_status == 'completed':
            new_status = 'closed'
        elif old_status in {'draft', 'open', 'reviewing', 'student_selected', 'closed', 'cancelled'}:
            new_status = old_status
        else:
            new_status = 'closed'

        ProjectRequest.objects.filter(pk=project_request.pk).update(
            project_type=request_type,
            status=new_status,
            created_project=first_project,
        )

    status_map = {
        'draft': ('draft', 'idea'),
        'in_review': ('pending', 'planning'),
        'approved': ('approved', 'planning'),
        'in_progress': ('approved', 'in_progress'),
        'completed': ('approved', 'completed'),
    }
    for project in Project.objects.select_related('project_request').all().iterator():
        approval_status, development_status = status_map.get(project.status, ('draft', 'idea'))
        if project.project_request_id and project.project_request.project_type_id:
            project_type_id = project.project_request.project_type_id
        else:
            project_type_id = project_types['INDEPENDENT'].pk
        public_legacy_status = project.status in {'in_progress', 'completed'}
        visibility = 'private' if project.is_private or not public_legacy_status else 'public'
        Project.objects.filter(pk=project.pk).update(
            project_type_id=project_type_id,
            creation_source='LEGACY',
            approval_status=approval_status,
            development_status=development_status,
            visibility=visibility,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0009_projectprogram_project_approval_status_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_and_map, migrations.RunPython.noop),
    ]
