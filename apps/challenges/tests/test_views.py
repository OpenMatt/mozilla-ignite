# Note: not using cStringIO here because then we can't set the "filename"
from StringIO import StringIO

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import SUCCESS
from django.core.urlresolvers import reverse
from django.db.models import Max
from django.http import Http404
from django.test.client import Client
from mock import Mock, patch
from nose.tools import assert_equal, with_setup
import test_utils

from commons.middleware import LocaleURLMiddleware
from challenges import views
from challenges.models import Challenge, Submission, Phase, Category, ExternalLink
from challenges.tests.fixtures import (challenge_setup, challenge_teardown,
                                       create_users, create_submissions)
from ignite.tests.decorators import ignite_skip, ignite_only
from projects.models import Project


# Apply this decorator to a test to turn off the middleware that goes around
# inserting 'en_US' redirects into all the URLs
suppress_locale_middleware = patch.object(LocaleURLMiddleware,
                                          'process_request',
                                          lambda *args: None)


def _build_request(path=None):
    request = Mock()
    request.path = path
    request._messages = []  # Stop messaging code trying to iterate a Mock
    return request


@ignite_skip
@with_setup(challenge_setup, challenge_teardown)
def test_show_challenge():
    """Test the view to show an individual challenge."""
    request = _build_request('/my-project/my-challenge/')
    response = views.show(request, 'my-project', 'my-challenge')
    assert_equal(response.status_code, 200)


class MessageTestCase(test_utils.TestCase):
    """Test case class to check messaging."""
    
    def assertSuccessMessage(self, response):
        """Assert that there is a success message in the given response."""
        self.assertEqual(len(response.context['messages']), 1)
        self.assertEqual(list(response.context['messages'])[0].level, SUCCESS)


class ChallengeEntryTest(test_utils.TestCase):
    # Need to inherit from this base class to get Jinja2 template hijacking
    
    def setUp(self):
        challenge_setup()
    
    def tearDown(self):
        challenge_teardown()
    
    @ignite_skip
    @suppress_locale_middleware
    def test_no_entries(self):
        """Test that challenges display ok without any entries."""
        response = self.client.get(Challenge.objects.get().get_absolute_url())
        assert_equal(response.status_code, 200)
        # Make sure the entries are present and in reverse creation order
        assert_equal(len(response.context['entries'].object_list), 0)
    
    @ignite_skip
    @suppress_locale_middleware
    def test_challenge_entries(self):
        """Test that challenge entries come through to the challenge view."""
        submission_titles = create_submissions(3)
        response = self.client.get(Challenge.objects.get().get_entries_url())
        assert_equal(response.status_code, 200)
        # Make sure the entries are present and in reverse creation order
        assert_equal([s.title for s in response.context['entries'].object_list],
                     list(reversed(submission_titles)))
    
    @suppress_locale_middleware
    def test_entries_view(self):
        """Test the dedicated entries view.
        
        This is currently a thin proxy onto the challenge view, hence this test
        being practically identical to the one above.
        
        """
        submission_titles = create_submissions(4)
        response = self.client.get(Challenge.objects.get().get_entries_url())
        assert_equal(response.status_code, 200)
        # Make sure the entries are present and in reverse creation order
        assert_equal([s.title for s in response.context['entries'].object_list],
                     list(reversed(submission_titles)))
    
    @suppress_locale_middleware
    def test_hidden_entries(self):
        """Test that draft entries are not visible on the entries page."""
        create_submissions(3)
        submissions = Submission.objects.all()
        hidden_submission = submissions[0]
        hidden_submission.is_draft = True
        hidden_submission.save()
        
        response = self.client.get(Challenge.objects.get().get_entries_url())
        # Check the draft submission is hidden
        assert_equal(set(response.context['entries'].object_list),
                     set(submissions[1:]))
    
    @ignite_only
    def test_winning_entries(self):
        """Test the winning entries view."""
        create_submissions(5)
        winners = Submission.objects.all()[1:3]
        for entry in winners:
            entry.is_winner = True
            entry.save()
        
        response = self.client.get(reverse('entries_winning'))
        self.assertEqual(set(e.title for e in response.context['entries']),
                         set(e.title for e in winners))


# Add this dictionary to a form for no external links
BLANK_EXTERNALS = {'externals-TOTAL_FORMS': '1',
                   'externals-INITIAL_FORMS': '0',
                   'externals-MAX_NUM_FORMS': ''}


def _build_links(initial_count, *forms):
    prefix = 'externals'
    form_data = {}
    form_data.update({'%s-TOTAL_FORMS' % prefix: str(len(forms)),
                      '%s-INITIAL_FORMS' % prefix: str(initial_count),
                      '%s-MAX_NUM_FORMS' % prefix: ''})
    for i, form in enumerate(forms):
        for key, value in form.iteritems():
            form_data['%s-%s-%s' % (prefix, i, key)] = value
    
    return form_data


def _form_from_link(link_object):
    return dict((k, getattr(link_object, k)) for k in ['id', 'name', 'url'])


class CreateEntryTest(test_utils.TestCase):
    """Tests related to posting a new entry."""
    
    def setUp(self):
        challenge_setup()
        self.category_id = Category.objects.get().id
        self.project_slug, self.challenge_slug = (Project.objects.get().slug,
                                                  Challenge.objects.get().slug)
        self.entry_form_path = '/en-US/%s/challenges/%s/entries/add/' % \
                               (self.project_slug, self.challenge_slug)
        create_users()
    
    def tearDown(self):
        challenge_teardown()
    
    @ignite_skip
    def test_anonymous_form(self):
        """Check we can't display the entry form without logging in."""
        response = self.client.get(self.entry_form_path)
        # Check it's some form of redirect
        assert response.status_code in xrange(300, 400)
    
    @ignite_skip
    def test_anonymous_post(self):
        """Check we can't post an entry without logging in."""
        form_data = {'title': 'Submission',
                     'brief_description': 'A submission',
                     'description': 'A submission of shining wonderment.',
                     'created_by': User.objects.get(username='alex').id,
                     'category': self.category_id}
        response = self.client.post(self.entry_form_path, data=form_data)
        assert response.status_code in xrange(300, 400)
        assert_equal(Submission.objects.count(), 0)
    
    @ignite_skip
    def test_display_form(self):
        """Test the new entry form."""
        self.client.login(username='alex', password='alex')
        response = self.client.get(self.entry_form_path)
        assert_equal(response.status_code, 200)
        # Check nothing gets created
        assert_equal(Submission.objects.count(), 0)
    
    @ignite_skip
    def test_submit_form(self):
        self.client.login(username='alex', password='alex')
        alex = User.objects.get(username='alex')
        form_data = {'title': 'Submission',
                     'brief_description': 'A submission',
                     'description': 'A submission of shining wonderment.',
                     'created_by': alex.get_profile(),
                     'category': self.category_id}
        
        form_data.update(BLANK_EXTERNALS)
        response = self.client.post(self.entry_form_path, data=form_data,
                                    follow=True)
        redirect_target = '/en-US/%s/challenges/%s/entries/' % \
                          (self.project_slug, self.challenge_slug)
        self.assertRedirects(response, redirect_target)
        # Make sure we actually created the submission
        assert_equal([s.description for s in Submission.objects.all()],
                     ['A submission of shining wonderment.'])
        submission = Submission.objects.get()
        assert_equal(submission.challenge.slug, self.challenge_slug)
        assert_equal(submission.created_by.user, alex)
    
    @ignite_skip
    def test_invalid_form(self):
        """Test that an empty form submission fails with errors."""
        self.client.login(username='alex', password='alex')
        response = self.client.post(self.entry_form_path, data=BLANK_EXTERNALS)
        # Not so fussed about authors: we'll be re-working that soon enough
        
        for k in ['Title', 'Summary']:
            assert k in response.context['errors'], 'Missing error key %s' % k
        assert_equal(Submission.objects.count(), 0)
    
    @ignite_skip
    def test_bad_image(self):
        """Test that a bad image is discarded."""
        self.client.login(username='alex', password='alex')
        alex = User.objects.get(username='alex')
        
        bad_image_file = StringIO('kitten pictures')
        bad_image_file.name = 'kittens.jpg'
        
        form_data = {'title': 'Submission',
                     'brief_description': 'A submission',
                     'description': 'A submission of shining wonderment.',
                     'created_by': alex.get_profile(),
                     'category': self.category_id,
                     'sketh_note': bad_image_file}
        
        form_data.update(BLANK_EXTERNALS)
        response = self.client.post(self.entry_form_path, data=form_data)
        
        assert response.context['errors'].get('Napkin sketch')
        assert response.context['form']['sketh_note'].value() is None
        assert_equal(Submission.objects.count(), 0)


@ignite_skip
@with_setup(challenge_setup, challenge_teardown)
def test_challenge_not_found():
    """Test behaviour when a challenge doesn't exist."""
    request = _build_request('/my-project/not-a-challenge/')
    try:
        response = views.show(request, 'my-project', 'not-a-challenge')
    except Http404:
        pass
    else:
        assert_equal(response.status_code, 404)


@ignite_skip
@with_setup(challenge_setup, challenge_teardown)
def test_wrong_project():
    """Test behaviour when the project and challenge don't match."""
    project_fields = {'name': 'Another project', 'slug': 'another-project',
                      'description': "Not the project you're looking for",
                      'long_description': 'Nothing to see here'}
    other_project = Project.objects.create(**project_fields)
    request = _build_request('/another-project/my-challenge/')
    # We either want 404 by exception or by response code here: either is fine
    try:
        response = views.show(request, 'another-project', 'my-challenge')
    except Http404:
        pass
    else:
        assert_equal(response.status_code, 404)


class ShowEntryTest(test_utils.TestCase):
    """Test functionality of the single entry view."""
    
    def setUp(self):
        challenge_setup()
        create_users()
        alex_profile = User.objects.get(username='alex').get_profile()
        s = Submission.objects.create(phase=Phase.objects.get(),
                                      title='A submission',
                                      brief_description='My submission',
                                      description='My wonderful submission',
                                      created_by=alex_profile,
                                      category=Category.objects.get())
        s.save()
        
        self.submission_path = s.get_absolute_url()
    
    @suppress_locale_middleware
    def test_show_entry(self):
        response = self.client.get(self.submission_path)
        assert_equal(response.status_code, 200)
    
    @suppress_locale_middleware
    def test_entry_not_found(self):
        # Get an ID that doesn't exist
        bad_id = Submission.objects.aggregate(max_id=Max('id'))['max_id'] + 1
        bad_path = '/my-project/challenges/my-challenge/entries/%d/' % bad_id
        response = self.client.get(bad_path)
        assert_equal(response.status_code, 404, response.content)


class EditEntryTest(MessageTestCase):
    """Test functionality of the edit entry view."""
    
    def setUp(self):
        challenge_setup()
        create_users()
        
        admin = User.objects.create_user('admin', 'admin@example.com',
                                         password='admin')
        admin.is_superuser = True
        admin.save()
        
        # Fill in the profile name to stop nag redirects
        admin_profile = admin.get_profile()
        admin_profile.name = 'Admin Adminson'
        admin_profile.save()
        
        alex_profile = User.objects.get(username='alex').get_profile()
        create_submissions(1, creator=alex_profile)
        
        entry = Submission.objects.get()
        self.view_path = entry.get_absolute_url()
        self.edit_path = entry.get_edit_url()
    
    def _edit_data(self, submission=None):
        if submission is None:
            submission = Submission.objects.get()
        return dict(title=submission.title,
                    brief_description='A submission',
                    description='A really, seriously good submission',
                    category=submission.category.id)
    
    @suppress_locale_middleware
    def test_edit_form(self):
        self.client.login(username='alex', password='alex')
        
        response = self.client.get(self.edit_path)
        assert_equal(response.status_code, 200)
    
    @suppress_locale_middleware
    def test_edit(self):
        self.client.login(username='alex', password='alex')
        data = self._edit_data()
        data.update(BLANK_EXTERNALS)
        response = self.client.post(self.edit_path, data, follow=True)
        self.assertRedirects(response, self.view_path)
        # Check for a success message
        self.assertSuccessMessage(response)
        
        assert_equal(Submission.objects.get().description, data['description'])
    
    @suppress_locale_middleware
    def test_anonymous_access(self):
        """Check that anonymous users can't get at the form."""
        response = self.client.get(self.edit_path)
        assert_equal(response.status_code, 302)
    
    @suppress_locale_middleware
    def test_anonymous_edit(self):
        """Check that anonymous users can't post to the form."""
        data = self._edit_data()
        data.update(BLANK_EXTERNALS)
        response = self.client.post(self.edit_path, data)
        assert_equal(response.status_code, 302)
        assert 'seriously' not in Submission.objects.get().description
    
    @suppress_locale_middleware
    def test_non_owner_access(self):
        """Check that non-owners cannot see the edit form."""
        self.client.login(username='bob', password='bob')
        response = self.client.get(self.edit_path)
        assert_equal(response.status_code, 403)
    
    @suppress_locale_middleware
    def test_non_owner_edit(self):
        """Check that users cannot edit each other's submissions."""
        self.client.login(username='bob', password='bob')
        data = self._edit_data()
        data.update(BLANK_EXTERNALS)
        response = self.client.post(self.edit_path, data)
        assert_equal(response.status_code, 403)
        assert 'seriously' not in Submission.objects.get().description
    
    @suppress_locale_middleware
    def test_admin_access(self):
        """Check that administrators can see the edit form."""
        self.client.login(username='admin', password='admin')
        response = self.client.get(self.edit_path)
        assert_equal(response.status_code, 200)
    
    @suppress_locale_middleware
    def test_admin_edit(self):
        """Check that administrators can edit submissions."""
        self.client.login(username='admin', password='admin')
        data = self._edit_data()
        data.update(BLANK_EXTERNALS)
        response = self.client.post(self.edit_path, data)
        self.assertRedirects(response, self.view_path)
        assert_equal(Submission.objects.get().description, data['description'])


class EditLinkTest(test_utils.TestCase):
    
    def setUp(self):
        challenge_setup()
        create_users()
        
        alex_profile = User.objects.get(username='alex').get_profile()
        create_submissions(1, creator=alex_profile)
        
        submission = Submission.objects.get()
        self.view_path = submission.get_absolute_url()
        self.edit_path = submission.get_edit_url()
        
        ExternalLink.objects.create(submission=submission, name='Foo',
                                    url='http://example.com/')
        ExternalLink.objects.create(submission=submission, name='Foo',
                                    url='http://example.net/')
        
        self.client.login(username='alex', password='alex')
    
    def _base_form(self):
        submission = Submission.objects.get()
        return {'title': submission.title,
                'brief_description': submission.brief_description,
                'description': submission.description,
                'category': submission.category.id}
    
    @suppress_locale_middleware
    def test_preserve_links(self):
        """Test submission when the links are not changed."""
        form_data = self._base_form()
        links = ExternalLink.objects.all()
        form_data.update(_build_links(2, *map(_form_from_link, links)))
        
        response = self.client.post(self.edit_path, form_data)
        
        self.assertRedirects(response, self.view_path)
        self.assertEqual(ExternalLink.objects.count(), 2)
    
    @suppress_locale_middleware
    def test_remove_links(self):
        """Test submission with blank link boxes.
        
        All the links should be deleted, as the forms are blank.
        
        """
        form_data = self._base_form()
        links = ExternalLink.objects.all()
        link_forms = [{'id': link.id} for link in links]
        form_data.update(_build_links(2, *link_forms))
        
        response = self.client.post(self.edit_path, form_data)
        self.assertRedirects(response, self.view_path)
        self.assertEqual(ExternalLink.objects.count(), 0)
    
    @suppress_locale_middleware
    def test_add_links(self):
        """Test adding links to a submission without any."""
        ExternalLink.objects.all().delete()
        
        form_data = self._base_form()
        link_forms = [{'name': 'Cheese', 'url': 'http://cheese.com/'},
                      {'name': 'Pie', 'url': 'http://en.wikipedia.org/wiki/Pie'}]
        form_data.update(_build_links(0, *link_forms))
        
        response = self.client.post(self.edit_path, form_data)
        
        self.assertRedirects(response, self.view_path)
        self.assertEqual(ExternalLink.objects.count(), 2)
        
        cheese_link = ExternalLink.objects.get(name='Cheese')
        self.assertEqual(cheese_link.url, 'http://cheese.com/')
        self.assertEqual(cheese_link.submission, Submission.objects.get())


class DeleteEntryTest(MessageTestCase):
    
    def setUp(self):
        challenge_setup()
        create_users()
        
        alex_profile = User.objects.get(username='alex').get_profile()
        create_submissions(1, creator=alex_profile)
        
        submission = Submission.objects.get()
        
        base_kwargs = {'project': Project.objects.get().slug,
                       'slug': Challenge.objects.get().slug}
        
        self.view_path = submission.get_absolute_url()
        self.delete_path = submission.get_delete_url()
    
    @suppress_locale_middleware
    def test_anonymous_delete_form(self):
        """Check that anonymous users can't get at the form."""
        response = self.client.get(self.delete_path)
        assert_equal(response.status_code, 302)
    
    @suppress_locale_middleware
    def test_anonymous_delete(self):
        """Check that anonymous users can't delete entries."""
        response = self.client.post(self.delete_path)
        assert_equal(response.status_code, 302)
    
    @suppress_locale_middleware
    def test_non_owner_access(self):
        """Check that non-owners cannot see the delete form."""
        self.client.login(username='bob', password='bob')
        response = self.client.get(self.delete_path)
        assert_equal(response.status_code, 403)
    
    @suppress_locale_middleware
    def test_non_owner_delete(self):
        """Check that users cannot delete each other's submissions."""
        self.client.login(username='bob', password='bob')
        response = self.client.post(self.delete_path, {})
        assert_equal(response.status_code, 403)
        assert Submission.objects.exists()
    
    @suppress_locale_middleware
    def test_delete_form(self):
        self.client.login(username='alex', password='alex')
        
        response = self.client.get(self.delete_path)
        assert_equal(response.status_code, 200)
    
    @suppress_locale_middleware
    def test_delete(self):
        self.client.login(username='alex', password='alex')
        response = self.client.post(self.delete_path, {}, follow=True)
        assert_equal(response.redirect_chain[0][1], 302)
        assert_equal(Submission.objects.count(), 0)
        
        self.assertSuccessMessage(response)
