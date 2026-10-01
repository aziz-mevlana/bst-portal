from copy import deepcopy
from datetime import timedelta
from queue import Queue
from threading import Barrier, Thread
import uuid
from unittest import skipUnless
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone
from .course_work_models import CourseProjectWork, CourseProjectParticipation, CoursePrivateEvaluation, CourseProjectAssignment
from .course_work_services import create_assignment, join_assignment, create_team, join_team, create_work, save_checkpoint
from .course_requirements import default_requirements
from .course_template_services import template_from_assignment, create_assignment_with_plan
from .milestone_services import submit_milestone, review_milestone, update_private_evaluation
from .models import Course, CourseInstructor, ProjectType, Project


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class FeedbackConcurrencyTests(TransactionTestCase):
    def setUp(self):
        def user(name,role):
            u=User.objects.create_user(name);u.profile.user_type=role;u.profile.class_level='2' if role=='student' else None;u.profile.save();return u
        self.teacher=user('feedback-race-teacher','teacher');self.students=[user(f'feedback-race-{i}','student') for i in range(3)]
        self.course,_=Course.objects.get_or_create(code='BST 207',defaults={'name':'Python Programlama'})
        ProjectType.objects.get_or_create(code='COURSE',defaults={'name':'Ders Projesi','slug':'ders-projesi','requires_course':True})
        CourseInstructor.objects.create(course=self.course,instructor=self.teacher)
        now=timezone.now();self.values=dict(topic='Race',mode='GROUP',min_team_size=2,max_team_size=3,
            join_deadline=now+timedelta(days=1),starts_at=now+timedelta(days=2),ends_at=now+timedelta(days=30))
        self.assignment=create_assignment(instructor=self.teacher,course=self.course,**self.values)
        self.checkpoint=save_checkpoint(assignment=self.assignment,actor=self.teacher,values=dict(title='Analiz',description='',order=1,due_at=now+timedelta(days=5),is_active=True,scoring_enabled=True,max_points=10))
        for student in self.students:join_assignment(token=self.assignment.invitation_token,student=student)
        self.team=create_team(assignment=self.assignment,student=self.students[0],name='Race Ekip')
        join_team(assignment=self.assignment,student=self.students[1],team_id=self.team.pk)

    def race(self,left,right):
        barrier=Barrier(2);output=Queue()
        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=15);output.put(('ok',operation()))
            except (ValidationError,PermissionDenied) as exc:output.put(('rejected',str(exc)))
            except Exception as exc:output.put(('error',repr(exc)))
            finally:connections.close_all()
        threads=[Thread(target=worker,args=(operation,)) for operation in (left,right)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=40);self.assertFalse(thread.is_alive())
        results=[output.get_nowait() for _ in threads];self.assertFalse(any(state=='error' for state,result in results),results)
        return results

    def work(self):
        return create_work(assignment=self.assignment,student=self.students[0],title='Race Project',idea='Idea')

    def test_two_members_initializing_keep_single_work_and_project(self):
        results=self.race(lambda:self.work().pk,lambda:create_work(assignment=self.assignment,student=self.students[1],title='Second',idea='Idea').pk)
        self.assertEqual(sum(state=='ok' for state,value in results),1)
        self.assertEqual(CourseProjectWork.objects.filter(team=self.team).count(),1)
        self.assertEqual(Project.objects.filter(creation_source='COURSE_ASSIGNMENT').count(),1)

    def test_join_during_initialization_updates_shared_project_membership(self):
        self.race(lambda:self.work().pk,lambda:join_team(assignment=self.assignment,student=self.students[2],team_id=self.team.pk).pk)
        work=CourseProjectWork.objects.get(team=self.team)
        self.assertEqual(set(work.project.team.values_list('pk',flat=True)),{u.pk for u in self.students})

    def test_requirement_edit_vs_submission_uses_one_complete_snapshot(self):
        work=self.work();milestone=work.project.milestones.get();requirements=default_requirements();requirements['TEXT']={'mode':'REQUIRED','min_count':1,'max_count':1}
        self.race(lambda:save_checkpoint(assignment=self.assignment,actor=self.teacher,checkpoint=self.checkpoint,
            values=dict(title='Analiz',description='',order=1,due_at=self.checkpoint.due_at,is_active=True,evidence_requirements=requirements)).pk,
            lambda:submit_milestone(milestone=milestone,actor=self.students[0]).pk)
        if milestone.submissions.exists():self.assertEqual(milestone.submissions.get().requirement_snapshot,default_requirements())
        self.assertLessEqual(milestone.submissions.count(),1)

    def test_revision_submit_vs_repeated_review_preserves_history(self):
        milestone=self.work().project.milestones.get();v1=submit_milestone(milestone=milestone,actor=self.students[0],references=[{'title':'Old','url':''}])
        review_milestone(submission=v1,actor=self.teacher,outcome='REVISION_REQUIRED',feedback='Revise')
        self.race(lambda:submit_milestone(milestone=milestone,actor=self.students[1],references=[{'title':'New','url':''}]).pk,
            lambda:review_milestone(submission=v1,actor=self.teacher,outcome='APPROVED').pk)
        self.assertEqual(milestone.submissions.count(),2);self.assertEqual(v1.references.get().title,'Old');self.assertEqual(v1.review.outcome,'REVISION_REQUIRED')

    def test_private_note_score_updates_reject_stale_writer(self):
        milestone=self.work().project.milestones.get();submission=submit_milestone(milestone=milestone,actor=self.students[0])
        review=review_milestone(submission=submission,actor=self.teacher,outcome='APPROVED',private_score=5,private_note='First')
        previous=review.private_evaluations.get()
        results=self.race(lambda:update_private_evaluation(review=review,actor=self.teacher,note='Left',score=6,expected_id=previous.pk).pk,
            lambda:update_private_evaluation(review=review,actor=self.teacher,note='Right',score=7,expected_id=previous.pk).pk)
        self.assertEqual(sum(state=='ok' for state,value in results),1)
        self.assertEqual(CoursePrivateEvaluation.objects.filter(review=review).count(),2)
        latest=review.private_evaluations.order_by('-pk').first();self.assertIn((latest.note,latest.score),[('Left',6),('Right',7)])

    def test_template_assignment_double_submit_is_single_snapshot(self):
        template=template_from_assignment(actor=self.teacher,assignment=self.assignment,name='Race Template')
        plan=[{**deepcopy(item),'due_at':self.checkpoint.due_at} for item in template.plan];token=uuid.uuid4()
        kwargs=dict(instructor=self.teacher,course=self.course,plan=plan,creation_token=token,template=template,**self.values)
        results=self.race(lambda:create_assignment_with_plan(**kwargs).pk,lambda:create_assignment_with_plan(**kwargs).pk)
        self.assertEqual(sum(state=='ok' for state,value in results),2)
        self.assertEqual(results[0][1],results[1][1])
        assignment=CourseProjectAssignment.objects.get(creation_token=token,instructor=self.teacher);self.assertEqual(assignment.checkpoints.count(),1)
