import hashlib
import re

from django.db import transaction

from .models import UnansweredQuestion


EMAIL_RE = re.compile(r'\b[^\s@]+@[^\s@]+\.[^\s@]+\b', re.IGNORECASE)
URL_RE = re.compile(r'\b(?:https?://|www\.)\S+', re.IGNORECASE)
LONG_NUMBER_RE = re.compile(r'(?<!\w)\+?[\d\s().-]{7,}(?!\w)')
WHITESPACE_RE = re.compile(r'\s+')


def safe_question_summary(question):
    """Analitik için e-posta, URL ve telefon/kimlik benzeri sayıları ayıkla."""
    summary = EMAIL_RE.sub('[e-posta]', question)
    summary = URL_RE.sub('[bağlantı]', summary)
    summary = LONG_NUMBER_RE.sub('[numara]', summary)
    summary = WHITESPACE_RE.sub(' ', summary).strip()
    return summary[:180] or '[boş soru]'


def record_unanswered_question(question, role='all'):
    safe_summary = safe_question_summary(question)
    question_hash = hashlib.sha256(safe_summary.casefold().encode('utf-8')).hexdigest()
    safe_role = role if role in {'all', 'student', 'teacher', 'alumni', 'staff'} else 'all'

    with transaction.atomic():
        item, created = UnansweredQuestion.objects.select_for_update().get_or_create(
            question_hash=question_hash,
            defaults={'safe_summary': safe_summary, 'roles': {safe_role: 1}},
        )
        if not created:
            roles = dict(item.roles or {})
            roles[safe_role] = int(roles.get(safe_role, 0)) + 1
            item.ask_count += 1
            item.roles = roles
            item.resolved_at = None
            item.save(update_fields=['ask_count', 'roles', 'resolved_at', 'last_asked_at'])
    return item
