from datetime import datetime
from importlib import import_module
from zoneinfo import ZoneInfo

from django.apps import apps
from django.db import connection
from django.test import TestCase

from .models import CapstoneTerm


migration = import_module('capstone.migrations.0009_activate_existing_2026_fall')
ISTANBUL = ZoneInfo('Europe/Istanbul')


class FallTermMigrationTests(TestCase):
    def run_seed(self):
        editor = type('Editor', (), {'connection': connection})()
        migration.ensure_fall_term(apps, editor)

    def make_term(self, year='2026-2027', semester='FALL', active=False):
        return CapstoneTerm.objects.create(
            academic_year=year, semester=semester,
            starts_at=datetime(2026, 9, 1, tzinfo=ISTANBUL),
            midterm_at=datetime(2026, 10, 1, tzinfo=ISTANBUL),
            final_at=datetime(2026, 12, 1, tzinfo=ISTANBUL),
            is_active=active,
        )

    def test_empty_database_creates_active_fall_with_official_aware_dates(self):
        self.assertFalse(CapstoneTerm.objects.exists())
        self.run_seed()
        term = CapstoneTerm.objects.get(academic_year='2026-2027', semester='FALL')
        self.assertTrue(term.is_active)
        self.assertEqual(term.starts_at, datetime(2026, 9, 14, tzinfo=ISTANBUL))
        self.assertEqual(term.midterm_at, datetime(2026, 11, 7, tzinfo=ISTANBUL))
        self.assertEqual(term.final_at, datetime(2026, 12, 26, tzinfo=ISTANBUL))
        self.assertEqual(CapstoneTerm.objects.filter(is_active=True).count(), 1)

    def test_second_run_is_idempotent(self):
        self.run_seed()
        first = CapstoneTerm.objects.get()
        self.run_seed()
        self.assertEqual(CapstoneTerm.objects.count(), 1)
        self.assertEqual(CapstoneTerm.objects.get().pk, first.pk)

    def test_existing_inactive_fall_becomes_active_without_date_changes(self):
        term = self.make_term()
        original_dates = (term.starts_at, term.midterm_at, term.final_at)
        self.run_seed()
        term.refresh_from_db()
        self.assertTrue(term.is_active)
        self.assertEqual((term.starts_at, term.midterm_at, term.final_at), original_dates)
        self.assertEqual(CapstoneTerm.objects.count(), 1)

    def test_existing_active_fall_is_unchanged(self):
        term = self.make_term(active=True)
        original_dates = (term.starts_at, term.midterm_at, term.final_at)
        self.run_seed()
        term.refresh_from_db()
        self.assertTrue(term.is_active)
        self.assertEqual((term.starts_at, term.midterm_at, term.final_at), original_dates)
        self.assertEqual(CapstoneTerm.objects.count(), 1)

    def test_another_active_term_kept_when_fall_is_missing(self):
        active = self.make_term(year='2025-2026', active=True)
        self.run_seed()
        active.refresh_from_db()
        fall = CapstoneTerm.objects.get(academic_year='2026-2027', semester='FALL')
        self.assertTrue(active.is_active)
        self.assertFalse(fall.is_active)
        self.assertEqual(CapstoneTerm.objects.filter(is_active=True).count(), 1)

    def test_another_active_term_kept_when_fall_exists_inactive(self):
        active = self.make_term(year='2025-2026', active=True)
        fall = self.make_term(active=False)
        original_dates = (fall.starts_at, fall.midterm_at, fall.final_at)
        self.run_seed()
        active.refresh_from_db()
        fall.refresh_from_db()
        self.assertTrue(active.is_active)
        self.assertFalse(fall.is_active)
        self.assertEqual((fall.starts_at, fall.midterm_at, fall.final_at), original_dates)
        self.assertEqual(CapstoneTerm.objects.filter(is_active=True).count(), 1)
