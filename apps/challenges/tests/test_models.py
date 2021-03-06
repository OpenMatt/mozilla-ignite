from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from mock import Mock, patch

from projects.models import Project
from challenges.models import (Challenge, Submission, Phase, Category,
                              ExclusionFlag, Judgement, JudgingCriterion,
                              PhaseCriterion)
from challenges.tests.fixtures import (challenge_setup, create_submissions,
                                       create_users)
from ignite.tests.decorators import ignite_skip


def _create_project_and_challenge():
    """Create and return a sample project with a sample challenge."""
    project = Project.objects.create(name='Project', slug='project',
                                          allow_participation=True)
    end_date = datetime.now() + timedelta(days=365)
    challenge = Challenge.objects.create(title='Challenge',
                                              slug='challenge',
                                              end_date=end_date,
                                              project=project)
    return project, challenge


class PermalinkTest(TestCase):
    
    def setUp(self):
        self.project, self.challenge = _create_project_and_challenge()
    
    @ignite_skip
    def test_permalink(self):
        self.assertEqual(self.challenge.get_absolute_url(),
                         '/project/challenges/challenge/')
    
    def tearDown(self):
        for model in [Challenge, Project]:
            model.objects.all().delete()


class SingleChallengePermalinkTest(TestCase):
    
    urls = 'challenges.tests.single_challenge_urls'
    
    def setUp(self):
        self.project, self.challenge = _create_project_and_challenge()
    
    def test_single_challenge_permalink(self):
        """Test permalink generation on an Ignite-style one-challenge site."""
        self.assertEqual(self.challenge.get_absolute_url(), '/')
    
    def tearDown(self):
        for model in [Challenge, Project]:
            model.objects.all().delete()


class EntriesToLive(TestCase):
    
    def setUp(self):
        self.project = Project.objects.create(
            name=u'A project for a test',
            allow_participation=True
        )
        self.challenge = Challenge.objects.create(
            title=u'Testing my submissions',
            end_date=u'2020-11-30 12:23:28',
            project=self.project,
            moderate=True
        )
        self.phase = Phase.objects.create(
            name=u'Phase 1', challenge=self.challenge, order=1
        )
        self.user = User.objects.create_user('bob', 'bob@example.com', 'bob')
        self.category = Category.objects.create(name='Misc', slug='misc')
        self.submission = Submission.objects.create(
            title=u'A submission to test',
            description=u'<h3>Testing bleach</h3>',
            phase=self.phase,
            created_by=self.user.get_profile(),
            category=self.category
        )
        self.submission_marked = Submission.objects.create(
            title=u'A submission with markdown',
            description=u'I **really** like cake',
            phase=self.phase,
            created_by=self.user.get_profile(),
            category=self.category
        )

    def test_phase_unicode(self):
        """Test the string representation of a phase."""
        self.assertEqual(unicode(self.phase),
                         u'Phase 1 (Testing my submissions)')
    
    def test_bleach_clearning(self):
        """
        Check that we're stripping out bad content - <h3> isn't in our 
        allowed list
        """
        self.assertEqual(self.submission.description_html,
                         '&lt;h3&gt;Testing bleach&lt;/h3&gt;')

    def test_markdown_conversion(self):
        """
        Check that we're converting markdown before outputting
        """
        self.assertEqual(self.submission_marked.description_html,
            '<p>I <strong>really</strong> like cake</p>')


class CategoryManager(TestCase):
    
    def setUp(self):
        self.project = Project.objects.create(
            name=u'Test Project',
            allow_participation=True
        )
        self.challenge = Challenge.objects.create(
            title=u'Testing categories',
            end_date=u'2020-11-30 12:23:28',
            description=u'Blah',
            project=self.project,
            moderate=False
        )
        self.phase = Phase.objects.create(
            name=u'Phase 1',
            order=1,
            challenge=self.challenge
        )
        self.user = User.objects.create_user('bob', 'bob@bob.com', 'bob')
        self.c1 = Category.objects.create(
            name=u'Testing',
            slug=u'testing'
        )
        self.c2 = Category.objects.create(
            name=u'Ross',
            slug=u'ross'
        )

    def test_initial_return(self):
        """
        Test that with no categories containing submissions returns nothing
        """
        self.assertEqual(Category.objects.get_active_categories(), False)

    def test_results_after_submission(self):
        """
        Test that we return only categories with submissions in
        """
        Submission.objects.create(
            title=u'Category',
            brief_description=u'Blah',
            description=u'Foot',
            phase=self.phase,
            created_by=self.user.get_profile(),
            category=self.c1
        )
        
        self.cats = Category.objects.get_active_categories()
        self.assertEqual(len(self.cats), 1)

    def tearDown(self):
        for model in [Challenge, Project, Phase, User, Category, Submission]:
            model.objects.all().delete()



class Phases(TestCase):

    def setUp(self):
        self.project, self.challenge = _create_project_and_challenge()
        
        self.p1 = Phase.objects.create(
            name=u'Phase 1',
            order=1,
            challenge=self.challenge,
            start_date = datetime.now(),
            end_date = datetime.now() + relativedelta( months = +1 )
        )
        self.p2 = Phase.objects.create(
            name=u'Phase 2',
            order=2,
            challenge=self.challenge,
            start_date = datetime.now() + relativedelta( months = +2 ),
            end_date = datetime.now() + relativedelta( months = +3 )
        )
 
    
    def test_get_current_open(self):
       current = Phase.objects.get_current_phase(self.challenge.slug)
       self.assertEqual(len(current), 1)
       self.assertEqual(current[0].name, 'Phase 1')
    
    def tearDown(self):
        for model in [Challenge, Project, Phase]:
            model.objects.all().delete()


class Criteria(TestCase):
    
    def test_value_range(self):
        c = JudgingCriterion(question='How awesome is this idea?', max_value=5)
        self.assertEqual(list(c.range), [0, 1, 2, 3, 4, 5])
    
    def test_good_range(self):
        c = JudgingCriterion(question='How awesome is this idea?', max_value=5)
        c.clean()
    
    def test_bad_range(self):
        c = JudgingCriterion(question='How awesome is this idea?',
                             max_value=-5)
        self.assertRaises(ValidationError, c.clean)
    
    def test_single_unit_range(self):
        c = JudgingCriterion(question='How awesome is this idea?', max_value=0)
        # A range of 0 to 0 is theoretically valid, but you can't weight it
        self.assertRaises(ValidationError, c.clean)


class JudgementScoring(TestCase):
    
    def setUp(self):
        challenge_setup()
        user = User.objects.create_user('bob', 'bob@example.com', 'bob')
        create_submissions(1)
        
        self.phase = Phase.objects.get()
        self.submission = Submission.objects.get()
        self.judge = user.get_profile()
    
    def test_equal_weighting(self):
        for i in range(4):
            c = JudgingCriterion.objects.create(question='Question %d' % i,
                                                max_value=10)
            PhaseCriterion.objects.create(phase=self.phase, criterion=c,
                                          weight=25)
        judgement = Judgement.objects.create(submission=self.submission,
                                             judge=self.judge)
        ratings = [3, 5, 7, 8]
        for criterion, rating in zip(JudgingCriterion.objects.all(), ratings):
            judgement.answers.create(criterion=criterion, rating=rating)
        
        self.assertTrue(judgement.complete)
        self.assertEqual(judgement.get_score(), Decimal('57.5'))
    
    def test_unequal_weighting(self):
        for i, weight in zip(range(4), [15, 25, 25, 35]):  # Total: 100
            c = JudgingCriterion.objects.create(question='Question %d' % i,
                                                max_value=10)
            PhaseCriterion.objects.create(phase=self.phase, criterion=c,
                                          weight=weight)
        judgement = Judgement.objects.create(submission=self.submission,
                                             judge=self.judge)
        ratings = [3, 5, 7, 8]
        criteria = JudgingCriterion.objects.all().order_by('question')
        for criterion, rating in zip(criteria, ratings):
            judgement.answers.create(criterion=criterion, rating=rating)
        
        self.assertTrue(judgement.complete)
        # 3 * 1.5 + 5 * 2.5 + 7 * 2.5 + 8 * 3.5
        self.assertEqual(judgement.get_score(), Decimal('62.5'))
    
    def test_incomplete_judgement(self):
        """Test that scoring an incomplete judgement raises an error."""
        for i in range(4):
            c = JudgingCriterion.objects.create(question='Question %d' % i,
                                                max_value=10)
            PhaseCriterion.objects.create(phase=self.phase, criterion=c,
                                          weight=25)
        judgement = Judgement.objects.create(submission=self.submission,
                                             judge=self.judge)
        ratings = [3, 5, 7]
        # Only three ratings, so zip will ignore the last criterion
        for criterion, rating in zip(JudgingCriterion.objects.all(), ratings):
            judgement.answers.create(criterion=criterion, rating=rating)
        
        self.assertFalse(judgement.complete)
        self.assertRaises(Judgement.Incomplete, judgement.get_score)
    
    def test_no_criteria(self):
        """Test behaviour when there are no criteria."""
        judgement = Judgement.objects.create(submission=self.submission,
                                             judge=self.judge)
        self.assertTrue(judgement.complete)
        self.assertEqual(judgement.get_score(), Decimal('0.00'))


class TestSubmissions(TestCase):
    
    def setUp(self):
        challenge_setup()
        create_submissions(3)
        cache.clear()
    
    def test_no_exclusions(self):
        self.assertEqual(Submission.objects.eligible().count(), 3)
    
    def test_exclusion(self):
        excluded = Submission.objects.all()[0]
        ExclusionFlag.objects.create(submission=excluded, notes='Blah blah')
        self.assertEqual(Submission.objects.eligible().count(), 2)
    
class DraftSubmissionTest(TestCase):
    
    def setUp(self):
        challenge_setup()
        create_users()
        alex_profile = User.objects.get(username='alex').get_profile()
        create_submissions(5, creator=alex_profile)
        
        self.draft_submission = Submission.objects.all()[0]
        self.draft_submission.is_draft = True
        self.draft_submission.save()
        
        cache.clear()
    
    def test_draft_not_public(self):
        assert self.draft_submission not in Submission.objects.visible()
    
    def test_non_draft_visible(self):
        """Test live submissions are visible to anyone and everyone."""
        alex, bob = [User.objects.get(username=u) for u in ['alex', 'bob']]
        s = Submission.objects.all()[3]
        assert s in Submission.objects.visible()
        for user in [alex, bob]:
            assert s in Submission.objects.visible(user=user)
            assert user.has_perm('challenges.view_submission', obj=s)
    
    def test_draft_not_visible_to_user(self):
        bob = User.objects.get(username='bob')
        assert self.draft_submission not in Submission.objects.visible(user=bob)
        assert not bob.has_perm('challenges.view_submission',
                                obj=self.draft_submission)
    
    def test_draft_visible_to_author(self):
        alex = User.objects.get(username='alex')
        assert self.draft_submission in Submission.objects.visible(user=alex)
        assert alex.has_perm('challenges.view_submission',
                             obj=self.draft_submission)
