"""Bounded evidence configuration shared by course plans and copied templates."""
from django.core.exceptions import ValidationError

KINDS = {'FILE': ('Dosya', 10), 'LINK': ('Link', 20),
         'REFERENCE': ('Kaynakça', 100), 'TEXT': ('Metin açıklaması', 1)}
MODES = [('DISABLED', 'Kullanma'), ('OPTIONAL', 'Opsiyonel'), ('REQUIRED', 'Zorunlu')]


def default_requirements():
    # Historical checkpoints accepted text/files/links freely. Preserve this.
    return {kind: {'mode': 'OPTIONAL', 'min_count': 0, 'max_count': limit}
            for kind, (_, limit) in KINDS.items()}


def validate_requirements(value):
    if not isinstance(value, dict) or set(value) != set(KINDS):
        raise ValidationError('Dört teslim türünün yapılandırması gereklidir.')
    for kind, (_, limit) in KINDS.items():
        config = value[kind]
        if not isinstance(config, dict) or set(config) != {'mode', 'min_count', 'max_count'}:
            raise ValidationError('Geçersiz teslim gereksinimi.')
        mode, minimum, maximum = config['mode'], config['min_count'], config['max_count']
        if mode not in dict(MODES) or type(minimum) is not int or not 0 <= minimum <= limit:
            raise ValidationError('Geçersiz teslim modu veya minimum sayı.')
        if maximum is not None and (type(maximum) is not int or not minimum <= maximum <= limit):
            raise ValidationError('Azami sayı minimumdan küçük veya sistem sınırından büyük olamaz.')
        if mode == 'REQUIRED' and minimum < 1:
            raise ValidationError('Zorunlu teslimde minimum en az 1 olmalıdır.')


def validate_evidence(requirements, *, files, links, references, note):
    validate_requirements(requirements)
    counts = {'FILE': len(files), 'LINK': len(links), 'REFERENCE': len(references), 'TEXT': int(bool(note.strip()))}
    for kind, count in counts.items():
        rule = requirements[kind]
        label, limit = KINDS[kind]
        if rule['mode'] == 'DISABLED' and count:
            raise ValidationError(f'{label}: bu kontrol noktasında kullanılmıyor.')
        if rule['mode'] == 'REQUIRED' and count < rule['min_count']:
            raise ValidationError(f'{label}: en az {rule["min_count"]} gerekli.')
        if count > (rule['max_count'] if rule['max_count'] is not None else limit):
            raise ValidationError(f'{label}: azami sayı aşıldı.')
