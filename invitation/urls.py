from django.conf import settings
from django.conf.urls import url
from django.views.generic import TemplateView

from invitation import utils
from invitation.views import (invite, invited, register, send_bulk_invitations,
                              token)

reg_backend_class = utils.get_registration_backend_class()
reg_backend = reg_backend_class().get_backend()

urlpatterns = [
    url(r'^invite/complete/$', TemplateView.as_view(template_name='invitation/invitation_complete.html'), name='invitation_complete'),
    url(r'^invite/$', invite, name='invitation_invite'),
    url(r'^invite/bulk/$', send_bulk_invitations, name='invitation_invite_bulk'),

    # TODO: allow custom key regex since can have custom key  generator
    url(r'^invited/(?P<invitation_key>\w+)&(?P<invitation_recipient>\S+@\S+)?/$', invited, name='invitation_invited'),
    url(r'^invited/.*', invited),
    url(r'^register/$', register, {'backend': reg_backend}, name='registration_register'),
]

if getattr(settings, 'INVITATION_USE_TOKEN', False):
    urlpatterns += url(r'^token/(?P<key>\w+)/$', token, name='invitation_token'),
