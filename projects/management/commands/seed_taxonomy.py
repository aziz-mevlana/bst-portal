from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils.text import slugify

from projects.models import ProjectCategory, Technology


TECHNOLOGIES = {
    'backend': ['Python', 'Django', 'FastAPI', 'Flask', 'Java', 'C', 'C++', 'C#', '.NET', 'PHP', 'Laravel', 'Node.js'],
    'frontend': ['JavaScript', 'TypeScript', 'React', 'Vue.js', 'Angular', 'Next.js', 'HTML', 'CSS', 'Tailwind CSS', 'Bootstrap'],
    'mobile': ['Flutter', 'Dart', 'Kotlin', 'Swift', 'React Native'],
    'database': ['PostgreSQL', 'MySQL', 'SQLite', 'MongoDB', 'Redis', 'Firebase'],
    'devops': ['Docker', 'Git', 'GitHub', 'Linux'],
    'cloud': ['AWS', 'Azure'],
    'ai_ml': ['TensorFlow', 'PyTorch', 'Scikit-learn', 'OpenCV'],
    'data_science': ['Pandas', 'NumPy'],
    'game': ['Unity', 'Unreal Engine', 'Godot'],
    'iot': ['Arduino', 'Raspberry Pi'],
    'design': ['Figma'],
}

CATEGORIES = [
    'Yapay Zekâ ve Makine Öğrenmesi', 'Web Uygulamaları', 'Mobil Uygulamalar',
    'Oyun Geliştirme', 'Veri Bilimi ve Analitik', 'Siber Güvenlik',
    'IoT ve Gömülü Sistemler', 'Robotik ve Otomasyon', 'Bulut Sistemleri',
    'Sağlık Teknolojileri', 'Eğitim Teknolojileri', 'Finans Teknolojileri',
    'Tarım Teknolojileri', 'Enerji ve Çevre', 'Akıllı Şehirler', 'E-Ticaret',
    'Sosyal Fayda', 'AR/VR', 'Kurumsal Yazılım', 'Diğer',
]

TECH_ALIASES = {
    'react.js': 'React', 'reactjs': 'React', 'vue': 'Vue.js', 'vuejs': 'Vue.js',
    'node': 'Node.js', 'nodejs': 'Node.js', 'dotnet': '.NET', 'c sharp': 'C#',
    'tailwind': 'Tailwind CSS', 'sklearn': 'Scikit-learn',
}
CATEGORY_ALIASES = {
    'yapay zeka ve makine öğrenmesi': 'Yapay Zekâ ve Makine Öğrenmesi',
    'web uygulaması': 'Web Uygulamaları', 'mobil uygulama': 'Mobil Uygulamalar',
}


def _normalized(value):
    return ' '.join(value.strip().casefold().split())


def _unique_slug(model, name, pk=None):
    base = slugify(name) or 'kayit'
    candidate = base
    counter = 2
    queryset = model.objects.exclude(pk=pk) if pk else model.objects.all()
    while queryset.filter(slug=candidate).exists():
        candidate = f'{base}-{counter}'
        counter += 1
    return candidate


def _copy_many_to_many_relations(duplicate, canonical):
    model = type(duplicate)
    for relation in model._meta.related_objects:
        if not relation.many_to_many:
            continue
        through = relation.through
        target_field = next(
            field for field in through._meta.fields
            if getattr(field.remote_field, 'model', None) is model
        )
        for row in through.objects.filter(**{target_field.name: duplicate}).iterator():
            values = {}
            for field in through._meta.fields:
                if field.primary_key or field is target_field:
                    continue
                values[field.name] = getattr(row, field.name)
            through.objects.get_or_create(**{target_field.name: canonical}, **values)


def _merge_duplicate(duplicate, canonical):
    _copy_many_to_many_relations(duplicate, canonical)
    aliases = list(getattr(canonical, 'aliases', []) or [])
    if duplicate.name not in aliases and hasattr(canonical, 'aliases'):
        aliases.append(duplicate.name)
        canonical.aliases = aliases
        canonical.save(update_fields=['aliases'])
    duplicate.is_active = False
    duplicate.save(update_fields=['is_active'])


class Command(BaseCommand):
    help = 'Teknoloji ve proje kategorilerini veri kaybı olmadan analiz eder ve güvenli biçimde yükler.'

    def add_arguments(self, parser):
        parser.add_argument('--analyze', action='store_true', help='Yalnızca olası tekrarları raporlar.')
        parser.add_argument('--merge-safe', action='store_true', help='Bilinen alias tekrarlarının ilişkilerini ana kayda taşır ve tekrarı pasifleştirir.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['analyze']:
            self._analyze()
            return
        for group, names in TECHNOLOGIES.items():
            for order, name in enumerate(names, 1):
                item = Technology.objects.filter(name__iexact=name).first()
                if item is None:
                    Technology.objects.create(name=name, group=group, sort_order=order)
                else:
                    changed = []
                    if item.name != item.name.strip():
                        item.name = item.name.strip(); changed.append('name')
                    if not item.slug:
                        item.slug = _unique_slug(Technology, item.name, item.pk); changed.append('slug')
                    if item.group == 'other':
                        item.group = group; changed.append('group')
                    if not item.is_active:
                        item.is_active = True; changed.append('is_active')
                    if changed:
                        item.save(update_fields=changed)
        for order, name in enumerate(CATEGORIES, 1):
            item = ProjectCategory.objects.filter(name__iexact=name).first()
            if item is None:
                ProjectCategory.objects.create(name=name, sort_order=order)
            else:
                changed = []
                if not item.slug:
                    item.slug = _unique_slug(ProjectCategory, item.name, item.pk); changed.append('slug')
                if not item.is_active:
                    item.is_active = True; changed.append('is_active')
                if changed:
                    item.save(update_fields=changed)
        if options['merge_safe']:
            self._merge_known_aliases()
        self.stdout.write(self.style.SUCCESS('Teknoloji ve kategori başlangıç verileri güvenli biçimde yüklendi.'))

    def _analyze(self):
        for model in (Technology, ProjectCategory):
            groups = {}
            for item in model.objects.all():
                groups.setdefault(_normalized(item.name), []).append(item)
            duplicates = [items for items in groups.values() if len(items) > 1]
            self.stdout.write(f'{model._meta.verbose_name}: {len(duplicates)} kesin tekrar grubu')
            for items in duplicates:
                self.stdout.write('  - ' + ', '.join(f'{item.name} (#{item.pk})' for item in items))

    def _merge_known_aliases(self):
        self._merge_alias_map(Technology, TECH_ALIASES)
        self._merge_alias_map(ProjectCategory, CATEGORY_ALIASES)

    def _merge_alias_map(self, model, aliases):
        for alias, canonical_name in aliases.items():
            canonical = model.objects.filter(name__iexact=canonical_name).first()
            if not canonical:
                continue
            for duplicate in model.objects.exclude(pk=canonical.pk):
                if _normalized(duplicate.name) == alias:
                    _merge_duplicate(duplicate, canonical)
                    self.stdout.write(f'Birleştirildi ve pasifleştirildi: {duplicate.name} -> {canonical.name}')
