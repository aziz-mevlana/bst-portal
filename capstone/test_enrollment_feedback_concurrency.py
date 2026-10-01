from datetime import timedelta
from queue import Queue
from threading import Barrier, Thread
from unittest import skipUnless
from django.contrib.auth.models import User
from django.db import connection, close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone
from core.models import AuditLog
from .models import CapstoneTerm, CapstoneEnrollment
from .academic_services import enroll_student, remove_enrollment


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class EnrollmentFeedbackConcurrencyTests(TransactionTestCase):
    def test_remove_readd_race_preserves_audit_and_allows_readd(self):
        admin=User.objects.create_user('feedback-enroll-race-admin',is_staff=True)
        student=User.objects.create_user('feedback-enroll-race-student');student.profile.class_level='4';student.profile.save()
        now=timezone.now();term=CapstoneTerm.objects.create(academic_year='2026-2027',semester='FALL',is_active=True,
            starts_at=now,midterm_at=now+timedelta(days=30),final_at=now+timedelta(days=60))
        enrollment=enroll_student(term=term,student=student,actor=admin);old_pk=enrollment.pk
        barrier=Barrier(2);output=Queue()
        def worker(operation):
            close_old_connections()
            try:barrier.wait(timeout=15);output.put(('ok',operation()))
            except Exception as exc:output.put(('error',repr(exc)))
            finally:connections.close_all()
        threads=[Thread(target=worker,args=(op,)) for op in
            (lambda:remove_enrollment(enrollment=enrollment,actor=admin,reason='Race'),lambda:enroll_student(term=term,student=student,actor=admin).pk)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=40);self.assertFalse(thread.is_alive())
        results=[output.get_nowait() for _ in threads];self.assertTrue(all(state=='ok' for state,value in results),results)
        final=enroll_student(term=term,student=student,actor=admin)
        self.assertEqual(CapstoneEnrollment.objects.filter(term=term,student=student,is_active=True).count(),1)
        self.assertNotEqual(final.pk,old_pk)
        self.assertTrue(AuditLog.objects.filter(action='capstone.enrollment_removed',metadata__enrollment_id=old_pk).exists())
