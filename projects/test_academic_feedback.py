from copy import deepcopy
from datetime import timedelta
import csv
import uuid
from pathlib import Path
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Notification
from .course_requirements import default_requirements, validate_requirements
from .course_work_models import CourseProjectWork, CourseProjectTemplate, CoursePrivateEvaluation
from .course_work_services import create_assignment, join_assignment, create_team, join_team, create_work, save_checkpoint, add_expectation, cancel_assignment
from .course_template_services import template_from_assignment, save_template, create_assignment_with_plan, BRIEF_FIELDS
from .milestone_services import submit_milestone, review_milestone, update_private_evaluation
from .models import Course, CourseCatalogEntry, CourseInstructor, ProjectMilestoneSubmission


def account(name, role='student'):
    u=User.objects.create_user(name, password='academic-test-password')
    u.profile.user_type=role; u.profile.class_level='2' if role=='student' else None; u.profile.save()
    return u


class AcademicFeedbackTests(TestCase):
    def setUp(self):
        self.teacher=account('feedback-teacher','teacher'); self.other=account('feedback-other','teacher')
        self.student=account('feedback-student'); self.second=account('feedback-second')
        self.course=Course.objects.get(code='BST 207')
        CourseInstructor.objects.create(course=self.course,instructor=self.teacher)
        self.now=timezone.now()
        self.values=dict(topic='Araştırma',purpose='Amaç',expectations='Beklentiler',mode='INDIVIDUAL',min_team_size=None,max_team_size=None,
            join_deadline=self.now+timedelta(days=1),starts_at=self.now+timedelta(days=2),ends_at=self.now+timedelta(days=30),repository_required=False)
        self.assignment=create_assignment(instructor=self.teacher,course=self.course,**self.values)
        self.checkpoint=save_checkpoint(assignment=self.assignment,actor=self.teacher,values=dict(title='Literatür',description='',order=1,due_at=self.now+timedelta(days=5),is_active=True))
        join_assignment(token=self.assignment.invitation_token,student=self.student)
        self.work=create_work(assignment=self.assignment,student=self.student,title='Özgün proje',idea='Çözüm fikri')
        self.milestone=self.work.project.milestones.get()

    def rules(self, kind, mode, minimum=0, maximum=None):
        config=default_requirements(); config[kind]=dict(mode=mode,min_count=minimum,max_count=maximum)
        self.checkpoint.evidence_requirements=config; self.checkpoint.save()
        self.milestone.refresh_from_db()
        return config

    def test_required_minimum_and_disabled_all_evidence_types(self):
        evidence={'FILE': {'files':[SimpleUploadedFile('a.txt',b'valid text')]},
            'LINK':{'links':['https://example.org/paper']},
            'REFERENCE':{'references':[{'title':'Bir kaynak','url':''}]},'TEXT':{'note':'Açıklama'}}
        for kind in evidence:
            with self.subTest(kind=kind):
                self.rules(kind,'DISABLED')
                with self.assertRaises(ValidationError): submit_milestone(milestone=self.milestone,actor=self.student,**evidence[kind])
                self.rules(kind,'REQUIRED',1)
                with self.assertRaises(ValidationError): submit_milestone(milestone=self.milestone,actor=self.student)
        self.assertEqual(ProjectMilestoneSubmission.objects.count(),0)

    def test_optional_minimum_does_not_require_evidence_and_maximum_is_enforced(self):
        self.rules('REFERENCE','OPTIONAL',2,2)
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone,actor=self.student,references=[{'title':str(i),'url':''} for i in range(3)])
        submit_milestone(milestone=self.milestone,actor=self.student)

    def test_requirement_configuration_rejects_forged_types_and_counts(self):
        for config in ({}, {'FILE':{}}, {**default_requirements(),'FILE':dict(mode='REQUIRED',min_count=0,max_count=10)},
                       {**default_requirements(),'FILE':dict(mode='OPTIONAL',min_count=2,max_count=1)},
                       {**default_requirements(),'TEXT':dict(mode='OPTIONAL',min_count=True,max_count=1)}):
            with self.subTest(config=config), self.assertRaises(ValidationError): validate_requirements(config)

    def test_zero_maximum_is_displayed_and_enforced(self):
        from .course_work_forms import CourseEvidenceForm
        self.rules('LINK','OPTIONAL',0,0)
        form=CourseEvidenceForm(checkpoint=self.checkpoint)
        self.assertIn('azami 0',form.fields['evidence_links'].help_text)
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone,actor=self.student,links=['https://example.org/forged'])

    def test_private_fields_are_not_loaded_in_student_responses_and_scoped_on_post(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.checkpoint.scoring_enabled=True;self.checkpoint.save()
        submission=submit_milestone(milestone=self.milestone,actor=self.student)
        review=review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=7,private_note='EXCLUSIVE-PRIVATE-AUDIT')
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertNotContains(response,'EXCLUSIVE-PRIVATE-AUDIT')
        self.assertFalse(any('projects_courseprivateevaluation' in query['sql'] for query in queries))
        self.assertTrue(all(not hasattr(item,'review_form') for item in response.context['milestones']))
        self.client.force_login(self.teacher)
        another=create_assignment(instructor=self.teacher,course=self.course,**self.values)
        join_assignment(token=another.invitation_token,student=self.second)
        another_work=create_work(assignment=another,student=self.second,title='Başka proje',idea='Başka fikir')
        self.assertEqual(self.client.post(reverse('projects:course_private_evaluation_update',args=[another_work.pk,review.pk]),
            {'private_note':'forged','private_score':1,'expected_id':review.private_evaluations.get().pk}).status_code,404)
        self.assertEqual(self.client.post(reverse('projects:course_work_review',args=[another_work.pk,submission.pk]),
            {'outcome':'APPROVED'}).status_code,404)

    def test_disabled_score_forgery_and_cancelled_private_update_do_not_mutate(self):
        submission=submit_milestone(milestone=self.milestone,actor=self.student)
        self.client.force_login(self.teacher)
        self.client.post(reverse('projects:course_work_review',args=[self.work.pk,submission.pk]),
            {'outcome':'APPROVED','private_score':'0','private_note':'forged'})
        self.assertFalse(hasattr(ProjectMilestoneSubmission.objects.get(pk=submission.pk),'review'))
        review=review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED')
        previous=review.private_evaluations.get()
        self.client.post(reverse('projects:course_private_evaluation_update',args=[self.work.pk,review.pk]),
            {'private_score':'0','expected_id':previous.pk})
        self.assertEqual(review.private_evaluations.count(),1)
        cancel_assignment(assignment=self.assignment,actor=self.teacher,reason='İptal')
        response=self.client.post(reverse('projects:course_private_evaluation_update',args=[self.work.pk,review.pk]),
            {'private_note':'cancelled-forgery','expected_id':previous.pk})
        self.assertRedirects(response,reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertEqual(review.private_evaluations.count(),1)
        with self.assertRaises((PermissionDenied,ValidationError)):
            update_private_evaluation(review=review,actor=self.teacher,note='cancelled',score=None,expected_id=previous.pk)

    @override_settings(PRIVATE_MEDIA_ROOT='/tmp/bst-academic-test-private')
    def test_revision_keeps_own_files_links_references_and_requirement_snapshot(self):
        config=self.rules('REFERENCE','REQUIRED',2)
        v1=submit_milestone(milestone=self.milestone,actor=self.student,note='v1',links=['https://example.org/v1'],
            files=[SimpleUploadedFile('first.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf')],references=[{'title':'Bir','url':''},{'title':'İki','url':'https://example.org/ref'}])
        review_milestone(submission=v1,actor=self.teacher,outcome='REVISION_REQUIRED',feedback='Kaynakları iyileştirin')
        self.rules('REFERENCE','REQUIRED',3)
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone,actor=self.student,references=[{'title':'Bir','url':''},{'title':'İki','url':''}])
        v2=submit_milestone(milestone=self.milestone,actor=self.student,references=[{'title':str(i),'url':''} for i in range(3)])
        self.assertEqual(v1.references.count(),2); self.assertEqual(v2.references.count(),3)
        self.assertEqual(v1.links.count(),1); self.assertEqual(v1.files.count(),1)
        self.assertEqual(v1.requirement_snapshot,config); self.assertEqual(v2.requirement_snapshot['REFERENCE']['min_count'],3)
        self.assertTrue(v1.files.first().file.storage.exists(v1.files.first().file.name))
        with self.assertRaises(ValidationError): v1.references.first().delete()

    def test_private_note_score_history_completion_and_no_student_or_notification_leak(self):
        self.checkpoint.scoring_enabled=True;self.checkpoint.max_points=10;self.checkpoint.save()
        submission=submit_milestone(milestone=self.milestone,actor=self.student)
        review=review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=7,private_note='SECRET-NOTE-EXCLUSIVE')
        evaluation=review.private_evaluations.get()
        update_private_evaluation(review=review,actor=self.teacher,note='SECOND-SECRET',score=8,expected_id=evaluation.pk)
        self.assertEqual(review.private_evaluations.count(),2)
        self.assertEqual(self.milestone.state,'APPROVED'); self.assertIsNone(review.score);self.assertIsNone(self.work.project.milestone_score)
        self.client.force_login(self.teacher)
        teacher=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertContains(teacher,'SECRET-NOTE-EXCLUSIVE');self.assertContains(teacher,'Puan: 7 / 10');self.assertContains(teacher,'8 / 10')
        self.client.force_login(self.student)
        student=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertNotContains(student,'SECRET-NOTE');self.assertNotContains(student,'Gizli Akademisyen');self.assertNotContains(student,'Puan:')
        self.assertNotIn('private_total',student.context)
        self.assertFalse(Notification.objects.filter(message__contains='SECRET').exists())
        self.assertEqual(self.client.post(reverse('projects:course_private_evaluation_update',args=[self.work.pk,review.pk]),{'private_note':'hacked','expected_id':evaluation.pk}).status_code,404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('projects:course_work_detail',args=[self.work.pk])).status_code,404)

    def test_private_score_bounds_disabled_optional_and_stale_updates(self):
        submission=submit_milestone(milestone=self.milestone,actor=self.student)
        with self.assertRaises(ValidationError): review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=0)
        self.assertFalse(hasattr(ProjectMilestoneSubmission.objects.get(pk=submission.pk),'review'))
        self.checkpoint.scoring_enabled=True;self.checkpoint.max_points=10;self.checkpoint.save()
        for score in (-1,11):
            with self.assertRaises(ValidationError): review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=score)
        review=review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED')
        self.assertIsNone(review.private_evaluations.get().score)
        with self.assertRaises(ValidationError): update_private_evaluation(review=review,actor=self.teacher,note='stale',score=1,expected_id=0)

    def test_cancelled_history_retains_inactive_checkpoint_but_excludes_its_totals(self):
        self.checkpoint.scoring_enabled=True;self.checkpoint.save()
        submission=submit_milestone(milestone=self.milestone,actor=self.student)
        review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=7,private_note='HISTORY-ONLY')
        self.checkpoint.is_active=False;self.checkpoint.save()
        cancel_assignment(assignment=self.assignment,actor=self.teacher,reason='İptal')
        self.client.force_login(self.teacher)
        response=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertContains(response,'HISTORY-ONLY')
        self.assertEqual(response.context['approved'],0)
        self.assertEqual(response.context['total'],0)
        self.assertEqual(response.context['private_total'],{'earned':0,'maximum':0})
        self.client.force_login(self.student)
        response=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        self.assertNotContains(response,'HISTORY-ONLY')
        self.assertEqual(response.context['approved'],0)

    def test_already_joined_invite_after_expiry_direct_project_access(self):
        self.assignment.join_deadline=self.now-timedelta(days=1);self.assignment.save()
        self.assertEqual(join_assignment(token=self.assignment.invitation_token,student=self.student).student_id,self.student.pk)
        self.client.force_login(self.student)
        response=self.client.get(reverse('projects:course_invitation',args=[self.assignment.invitation_token]))
        self.assertContains(response,'zaten katıldınız');self.assertContains(response,'Projeyi Aç')
        self.assertNotContains(response,'Projeye Katıl');self.assertNotContains(response,'name="title"')

    def test_group_join_direct_shared_workspace_and_teacher_team_links(self):
        assignment=create_assignment(instructor=self.teacher,course=self.course,**{**self.values,'mode':'GROUP','min_team_size':2,'max_team_size':3})
        for student in (self.student,self.second):join_assignment(token=assignment.invitation_token,student=student)
        team=create_team(assignment=assignment,student=self.student,name='Ekip Alpha')
        join_team(assignment=assignment,student=self.second,team_id=team.pk)
        work=create_work(assignment=assignment,student=self.student,title='Ortak Proje',idea='Ortak fikir')
        self.client.force_login(self.second)
        response=self.client.get(reverse('projects:course_invitation',args=[assignment.invitation_token]))
        self.assertContains(response,reverse('projects:course_work_detail',args=[work.pk]));self.assertNotContains(response,'name="title"')
        self.assertEqual(self.client.get(reverse('projects:course_work_detail',args=[work.pk])).status_code,200)
        self.assertEqual(CourseProjectWork.objects.filter(team=team).count(),1)
        self.client.force_login(self.teacher)
        for section in ('teams','matrix'):
            response=self.client.get(reverse('projects:course_assignment_detail',args=[assignment.pk]),{'section':section})
            self.assertContains(response,'Ekip Alpha');self.assertContains(response,reverse('projects:course_work_detail',args=[work.pk]))
        self.assertContains(response,'position:sticky');self.assertContains(response,'overflow-x:auto')

    def test_active_dashboard_and_cancelled_readonly_history(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('dashboard:home')),'Özgün proje')
        cancel_assignment(assignment=self.assignment,actor=self.teacher,reason='İptal')
        home=self.client.get(reverse('dashboard:home'));self.assertNotContains(home,reverse('projects:course_work_detail',args=[self.work.pk]))
        listing=self.client.get(reverse('projects:course_my_assignments'))
        self.assertContains(listing,'Geçmiş Çalışmalar');self.assertContains(listing,'Geçmişi Görüntüle')
        self.assertEqual(self.client.get(reverse('projects:course_work_detail',args=[self.work.pk])).status_code,200)

    def test_disabled_evidence_fields_hidden_and_forged_post_rejected(self):
        self.checkpoint.evidence_requirements={kind:dict(mode='DISABLED',min_count=0,max_count=None) for kind in default_requirements()};self.checkpoint.save()
        self.client.force_login(self.student)
        page=self.client.get(reverse('projects:course_work_detail',args=[self.work.pk]))
        for name in ('completion_note','evidence_links','references','files'):
            self.assertNotContains(page,f'name="{name}"')
        url=reverse('projects:course_work_submit',args=[self.work.pk,self.milestone.pk])
        for data in ({'completion_note':'forged'},{'evidence_links':'https://example.org/forged'},{'references':'Forged source'}):
            self.client.post(url,data)
            self.assertEqual(self.milestone.submissions.count(),0)
        self.client.post(url,{'files':SimpleUploadedFile('forged.txt',b'forged evidence')})
        self.assertEqual(self.milestone.submissions.count(),0)

    def test_template_owner_snapshot_and_student_data_excluded(self):
        self.rules('REFERENCE','REQUIRED',5)
        self.checkpoint.scoring_enabled=True;self.checkpoint.save()
        add_expectation(checkpoint=self.checkpoint,actor=self.teacher,title='Bilimsel kaynaklar')
        submission=submit_milestone(milestone=self.milestone,actor=self.student,references=[{'title':str(i),'url':''} for i in range(5)])
        review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_note='PRIVATE TEMPLATE EXCLUDED',private_score=7)
        template=template_from_assignment(actor=self.teacher,assignment=self.assignment,name='Araştırma Şablonu')
        self.assertNotIn('due_at',template.plan[0]);self.assertNotIn('PRIVATE',str(template.plan));self.assertNotIn('Özgün proje',str(template.plan))
        token=uuid.uuid4(); plan=[{**deepcopy(template.plan[0]),'due_at':self.now+timedelta(days=10)}]
        created=create_assignment_with_plan(instructor=self.teacher,course=self.course,plan=plan,creation_token=token,template=template,**self.values)
        duplicate=create_assignment_with_plan(instructor=self.teacher,course=self.course,plan=plan,creation_token=token,template=template,**self.values)
        self.assertEqual(created.pk,duplicate.pk);self.assertEqual(created.participants.count(),0);self.assertEqual(created.works.count(),0)
        self.assertEqual(created.checkpoints.get().expected_items.get().title,'Bilimsel kaynaklar')
        changed=deepcopy(template.plan);changed[0]['title']='Yeni Tanım'
        save_template(actor=self.teacher,template=template,expected_version=0,values={'plan':changed})
        self.assertEqual(created.checkpoints.get().title,'Literatür')
        with self.assertRaises(PermissionDenied):save_template(actor=self.other,template=template,expected_version=1,values={'name':'Forgery'})
        self.client.force_login(self.other)
        for name in ('course_template_edit','course_template_archive'):
            url=reverse('projects:'+name,args=[template.pk])
            self.assertEqual((self.client.get(url) if name.endswith('edit') else self.client.post(url)).status_code,404)
        self.assertEqual(self.client.get(reverse('projects:course_assignment_create'),{'template':template.pk}).status_code,404)

    def test_template_plan_form_prefilled_editable_and_new_dates_blank(self):
        template=template_from_assignment(actor=self.teacher,assignment=self.assignment,name='Şablon')
        self.client.force_login(self.teacher)
        page=self.client.get(reverse('projects:course_assignment_create'),{'template':template.pk})
        self.assertContains(page,'Literatür');self.assertContains(page,'name="plan-0-due_at"');self.assertContains(page,'Şablondan Oluştur')
        self.assertNotContains(page,self.checkpoint.due_at.strftime('%Y-%m-%dT%H:%M'))
        self.assertEqual(self.client.get(reverse('projects:course_template_edit',args=[template.pk])).status_code,200)

    def test_checkpoint_configuration_post_and_cross_assignment_idor(self):
        self.client.force_login(self.teacher)
        values={'title':'Literatür','description':'','order':1,'due_at':self.checkpoint.due_at.strftime('%Y-%m-%d %H:%M:%S%z'),'is_active':'on','scoring_enabled':'on','max_points':12}
        for kind in default_requirements():
            values.update({f'{kind.lower()}_mode':'OPTIONAL',f'{kind.lower()}_min':0,f'{kind.lower()}_max':''})
        values.update(reference_mode='REQUIRED',reference_min=5,file_mode='DISABLED')
        response=self.client.post(reverse('projects:course_checkpoint_edit',args=[self.assignment.pk,self.checkpoint.pk]),values)
        self.assertEqual(response.status_code,302)
        self.checkpoint.refresh_from_db();self.assertEqual(self.checkpoint.evidence_requirements['REFERENCE']['min_count'],5)
        self.assertTrue(self.checkpoint.scoring_enabled);self.assertEqual(self.checkpoint.max_points,12)
        another=create_assignment(instructor=self.teacher,course=self.course,**self.values)
        self.assertEqual(self.client.post(reverse('projects:course_checkpoint_edit',args=[another.pk,self.checkpoint.pk]),values).status_code,404)

    def test_required_evidence_success_limits_and_each_revision_stands_alone(self):
        rules=default_requirements()
        rules.update(FILE={'mode':'REQUIRED','min_count':2,'max_count':2},LINK={'mode':'REQUIRED','min_count':2,'max_count':2},
                     REFERENCE={'mode':'REQUIRED','min_count':5,'max_count':5},TEXT={'mode':'REQUIRED','min_count':1,'max_count':1})
        self.checkpoint.evidence_requirements=rules;self.checkpoint.save();self.milestone.refresh_from_db()
        def evidence():
            return {'note':'Tam açıklama','links':['https://example.org/one','https://example.org/two'],
                'files':[SimpleUploadedFile(f'{i}.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf') for i in range(2)],
                'references':[{'title':str(i),'url':''} for i in range(5)]}
        for field in ('files','links','references'):
            values=evidence();values[field]=values[field][:-1]
            with self.subTest(field=field),self.assertRaises(ValidationError):submit_milestone(milestone=self.milestone,actor=self.student,**values)
        first=submit_milestone(milestone=self.milestone,actor=self.student,**evidence())
        self.assertEqual(first.files.count(),2);self.assertEqual(first.links.count(),2);self.assertEqual(first.references.count(),5)
        review_milestone(submission=first,actor=self.teacher,outcome='REVISION_REQUIRED',feedback='Revize edin')
        with self.assertRaises(ValidationError):submit_milestone(milestone=self.milestone,actor=self.student,note='Önceki kanıtları kullan')

    def test_template_manual_create_edit_archive_and_assignment_snapshot_via_posts(self):
        self.client.force_login(self.teacher)
        values={'name':'Kişisel Şablon','topic':'Özgün konu','purpose':'Amaç','expectations':'','mode':'INDIVIDUAL',
            'min_team_size':'','max_team_size':'','version':0,'plan-TOTAL_FORMS':0,'plan-INITIAL_FORMS':0,'plan-MAX_NUM_FORMS':100}
        response=self.client.post(reverse('projects:course_template_create'),values)
        self.assertEqual(response.status_code,302);template=CourseProjectTemplate.objects.get(name='Kişisel Şablon')
        values['name']='Düzenlenmiş Şablon'
        response=self.client.post(reverse('projects:course_template_edit',args=[template.pk]),values)
        self.assertEqual(response.status_code,302);template.refresh_from_db();self.assertEqual(template.name,'Düzenlenmiş Şablon')
        token=str(uuid.uuid4())
        data={**self.values,'course':self.course.pk,'template_id':template.pk,'creation_token':token,
            'plan-TOTAL_FORMS':0,'plan-INITIAL_FORMS':0,'plan-MAX_NUM_FORMS':100}
        for key in ('join_deadline','starts_at','ends_at'):data[key]=data[key].strftime('%Y-%m-%d %H:%M:%S%z')
        for key in ('min_team_size','max_team_size'):data[key]=''
        data.pop('repository_required')
        first=self.client.post(reverse('projects:course_assignment_create'),data)
        second=self.client.post(reverse('projects:course_assignment_create'),data)
        self.assertEqual(first.status_code,302);self.assertEqual(first.url,second.url)
        self.assertEqual(self.teacher.course_project_assignments.filter(creation_token=token).count(),1)
        self.client.post(reverse('projects:course_template_archive',args=[template.pk]),{'version':template.version})
        template.refresh_from_db();self.assertTrue(template.is_archived)
        self.assertEqual(self.client.get(reverse('projects:course_assignment_create'),{'template':template.pk}).status_code,404)

    def test_work_page_queries_do_not_grow_with_checkpoint_count(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.force_login(self.teacher)
        url=reverse('projects:course_work_detail',args=[self.work.pk])
        self.client.get(url)  # Warm the shared shell/template caches.
        with CaptureQueriesContext(connection) as first:self.client.get(url)
        for order in range(2,7):
            save_checkpoint(assignment=self.assignment,actor=self.teacher,values=dict(title=f'Kontrol {order}',description='',order=order,due_at=self.now+timedelta(days=order+3),is_active=True))
        with CaptureQueriesContext(connection) as many:self.client.get(url)
        self.assertLessEqual(len(many),len(first)+1)

    def test_forged_template_identifiers_and_other_teachers_are_404(self):
        self.client.force_login(self.teacher)
        for template_id in ('garbage','-1','99999999999999999999999999999999'):
            self.assertEqual(self.client.get(reverse('projects:course_assignment_create'),{'template':template_id}).status_code,404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('projects:course_assignment_detail',args=[self.assignment.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('projects:course_checkpoint_edit',args=[self.assignment.pk,self.checkpoint.pk]),{}).status_code,404)


class OfficialCatalogTests(TestCase):
    def test_independent_pdf_semester_transcription_and_collision_names(self):
        # Independently read from the PDF tables during final audit, not from seed/CSV.
        semesters={
            1:[103,105],2:[104],3:[201,203,205,207,209,211],4:[202,204,206,208,210,212],
            5:[301,303,305,307,321,323,325,337,327,329,399,331,333,335],
            6:[302,304,306,308,326,328,330,332,334,336,392,320,322,324],
            7:[401,403,405,407,421,499,425,427,423,429,431],
            8:[402,404,406,420,422,498,424,426,428,430,432,434,436],
        }
        for semester, codes in semesters.items():
            entries=CourseCatalogEntry.objects.filter(academic_year='2026-2027',is_active=True,
                class_level=(semester+1)//2,semester='FALL' if semester%2 else 'SPRING')
            self.assertEqual(set(entries.values_list('course__code',flat=True)),{f'BST {code}' for code in codes})
        for code,names in {
            'BST 421':'İletişim Teknikleri / Yapay Zekâ Programlama',
            'BST 425':'Kamu Ekonomisi / Gömülü Sistemler',
            'BST 427':'Yerel Yönetimler / Bulanık Mantık',
        }.items():
            course=Course.objects.get(code=code)
            self.assertEqual(course.name,names)
            self.assertEqual(course.catalog_entries.get(academic_year='2026-2027').display_name,names)
            self.assertIn(names,str(course))

    def test_catalog_matches_all_pdf_codes_including_electives_and_early_exceptions(self):
        rows=list(csv.DictReader(open(Path(__file__).resolve().parent.parent/'docs/academic-workflow/catalog.csv')))
        expected={(r['code'],int(r['semester'])) for r in rows}
        actual={(entry.course.code,entry.class_level*2-(entry.semester=='FALL')) for entry in CourseCatalogEntry.objects.filter(academic_year='2026-2027',is_active=True).select_related('course')}
        self.assertEqual(actual,expected);self.assertEqual(len(actual),67)
        self.assertEqual({code for code,semester in actual if semester<=2},{'BST 103','BST 105','BST 104'})
        self.assertTrue(all(code.startswith('BST ') for code,semester in actual))
        self.assertEqual(len(actual),len({code for code,semester in actual}))
        for code in ('BST 333','BST 335','BST 407','BST 427','BST 429'):
            self.assertIn(code,{code for code,semester in actual})
        self.assertIn('Bulanık Mantık',CourseCatalogEntry.objects.get(course__code='BST 427').display_name)
