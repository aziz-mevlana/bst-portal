from importlib import import_module
from datetime import timedelta
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class FeedbackMigrationTests(TransactionTestCase):
    def test_0030_to_latest_preserves_relationships_names_and_unique_tokens(self):
        old=[('projects','0030_courseprojectassignment_cancellation_reason_and_more')]
        executor=MigrationExecutor(connection); leaves=executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(old); apps=executor.loader.project_state(old).apps
            User=apps.get_model('auth','User');Course=apps.get_model('projects','Course');Entry=apps.get_model('projects','CourseCatalogEntry')
            Assignment=apps.get_model('projects','CourseProjectAssignment');Checkpoint=apps.get_model('projects','CourseAssignmentCheckpoint')
            teacher=User.objects.create(username='feedback-migration-teacher');student=User.objects.create(username='feedback-migration-student')
            course,_=Course.objects.get_or_create(code='BST 207',defaults={'name':'Python Programlama','slug':'feedback-python'});course.name='Historical title';course.code='bst207';course.save()
            entry,_=Entry.objects.get_or_create(course=course,academic_year='2026-2027',semester='FALL',defaults={'class_level':2,'display_name':'Python Programlama'}); entry_pk=entry.pk
            excluded=Course.objects.create(code='BST 102',name='Genel İşletme',slug='feedback-excluded')
            other_entry=Entry.objects.create(course=excluded,academic_year='2026-2027',semester='SPRING',class_level=1,display_name='Genel İşletme')
            now=timezone.now();assignments=[]
            for i in range(2):
                assignments.append(Assignment.objects.create(course=course,instructor=teacher,topic=f'Historic {i}',join_deadline=now+timedelta(days=1),starts_at=now+timedelta(days=2),ends_at=now+timedelta(days=20)))
            participation=apps.get_model('projects','CourseProjectParticipation').objects.create(assignment=assignments[0],student=student)
            checkpoint=Checkpoint.objects.create(assignment=assignments[0],title='Historic checkpoint',order=1,due_at=now+timedelta(days=3))
            executor=MigrationExecutor(connection);executor.migrate(leaves);new=executor.loader.project_state(leaves).apps
            self.assertEqual(new.get_model('projects','Course').objects.get(pk=course.pk).name,'Historical title')
            self.assertEqual(new.get_model('projects','CourseCatalogEntry').objects.get(pk=entry_pk).course_id,course.pk)
            self.assertFalse(new.get_model('projects','CourseCatalogEntry').objects.get(pk=other_entry.pk).is_active)
            self.assertTrue(new.get_model('projects','Course').objects.filter(pk=excluded.pk).exists())
            self.assertEqual(new.get_model('projects','CourseProjectParticipation').objects.get(pk=participation.pk).assignment_id,assignments[0].pk)
            new_assignments=new.get_model('projects','CourseProjectAssignment').objects.filter(pk__in=[a.pk for a in assignments])
            self.assertEqual(len(set(new_assignments.values_list('creation_token',flat=True))),2)
            rules=new.get_model('projects','CourseAssignmentCheckpoint').objects.get(pk=checkpoint.pk).evidence_requirements
            self.assertTrue(all(rule['mode']=='OPTIONAL' for rule in rules.values()))
            for code, names in {
                'BST 421': 'İletişim Teknikleri / Yapay Zekâ Programlama',
                'BST 425': 'Kamu Ekonomisi / Gömülü Sistemler',
                'BST 427': 'Yerel Yönetimler / Bulanık Mantık',
            }.items():
                self.assertEqual(new.get_model('projects','Course').objects.get(code=code).name, names)
            fix=import_module('projects.migrations.0033_disambiguate_catalog_course_names')
            collision=new.get_model('projects','Course').objects.get(code='BST 421')
            collision.name='Custom historical title';collision.save()
            with connection.schema_editor() as editor:
                fix.disambiguate_names(new,editor)
            collision.refresh_from_db();self.assertEqual(collision.name,'Custom historical title')
            collision.name='Yapay Zekâ Programlama';collision.save()
            with connection.schema_editor() as editor:
                fix.disambiguate_names(new,editor);fix.disambiguate_names(new,editor)
            collision.refresh_from_db();self.assertEqual(collision.name,'İletişim Teknikleri / Yapay Zekâ Programlama')
            catalog=import_module('projects.migrations.0031_restore_full_bst_catalog')
            before=list(new.get_model('projects','CourseCatalogEntry').objects.values_list('pk','course_id','display_name','is_active'))
            with connection.schema_editor() as editor:
                catalog.restore_catalog(new,editor);catalog.restore_catalog(new,editor)
            self.assertEqual(before,list(new.get_model('projects','CourseCatalogEntry').objects.values_list('pk','course_id','display_name','is_active')))
        finally:
            MigrationExecutor(connection).migrate(leaves)
