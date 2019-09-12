from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import render, render_to_response
from django.template import RequestContext
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from invitation import utils, models
from invitation.models import InvitationKey

import logging
logger = logging.getLogger(__name__)

reg_backend_class = utils.get_registration_backend_class()
reg_backend = reg_backend_class()
RegistrationForm = reg_backend.get_registration_form()
registration_template = reg_backend.get_registration_template()
registration_register = reg_backend.get_registration_view()

InvitationKeyForm = utils.get_invitation_form()

is_key_valid = InvitationKey.objects.is_key_valid
get_key = InvitationKey.objects.get_key
objs = InvitationKey.objects
remaining_invitations_for_user = objs.remaining_invitations_for_user


def invited(request, invitation_key=None, invitation_recipient=None,
            extra_context=None):
    if getattr(settings, 'INVITE_MODE', False):
        if extra_context is not None:
            extra_context = extra_context.copy()
        else:
            extra_context = {}
        valid_key_obj = is_key_valid(invitation_key)
        if invitation_key and valid_key_obj:
            template_name = 'invitation/invited.html'
            extra_context.update({'invitation_key': invitation_key})
        else:
            if invitation_key:
                extra_context.update({'invitation_key': invitation_key})
                ik = get_key(invitation_key)
                if ik:
                    if ik.key_expired():
                        extra_context.update({'expired_key': True})
                    else:
                        assert ik.uses_left == 0
                        extra_context.update({'no_uses_left_key': True})
                else:
                    extra_context.update({'invalid_key': True})
            else:
                extra_context.update({'no_key': True})
            template_name = 'invitation/wrong_invitation_key.html'

        if valid_key_obj:
            invitation_recipient = valid_key_obj.recipient() or \
                invitation_recipient
            extra_context\
                .update({'invitation_recipient': invitation_recipient})
            request.session['invitation_key'] = valid_key_obj.key
            request.session['invitation_recipient'] = invitation_recipient
            request.session['invitation_context'] = extra_context or {}

        return render(request, template_name, extra_context)
    else:
        return HttpResponseRedirect(reverse('registration_register'))


def register(request, backend, success_url=None,
             form_class=RegistrationForm,
             disallowed_url='registration_disallowed',
             post_registration_redirect=None,
             template_name=registration_template,
             wrong_template_name='invitation/wrong_invitation_key.html',
             extra_context=None):
    extra_context = extra_context is not None and extra_context.copy() or {}
    if getattr(settings, 'INVITE_MODE', False):
        invitation_key = request.REQUEST.get('invitation_key', False)
        if invitation_key:
            extra_context.update({'invitation_key': invitation_key})
            if is_key_valid(invitation_key):
                return registration_register(request, backend, success_url,
                                             form_class, disallowed_url,
                                             template_name, extra_context)
            else:
                extra_context.update({'invalid_key': True})
        else:
            extra_context.update({'no_key': True})
        return render(request, wrong_template_name, extra_context)
    else:
        return registration_register(request, backend, success_url, form_class,
                                     disallowed_url, template_name,
                                     extra_context)


@login_required
def invite(request, success_url=None,
           form_class=InvitationKeyForm,
           template_name='invitation/invitation_form.html',
           extra_context=None):
    extra_context = extra_context is not None and extra_context.copy() or {}
    remaining_invitations = remaining_invitations_for_user(request.user)
    if request.method == 'POST':
        form = form_class(data=request.POST, files=request.FILES,
                          remaining_invitations=remaining_invitations,
                          user=request.user)
        if form.is_valid():
            # check to see if the recipient is already a member (if there
            # is an email address)
            existing_user = None
            if 'email' in form.cleaned_data:
                email_addr = form.cleaned_data.get('email')
                try:
                    existing_user = User.objects.get(email=email_addr)
                    extra_context.update({'recipient_already_user': True})
                except User.DoesNotExist:
                    pass
            if existing_user is None:
                # TODO: make this changeable per request
                delivery_backend_class = utils.get_delivery_backend_class()
                delivery_backend = delivery_backend_class(form.cleaned_data)
                invite = delivery_backend.create_invitation(request.user)
                invite.send_to(delivery_backend)

                # success_url needs to be dynamically generated here; setting a
                # a default value using reverse() will cause circular-import
                # problems with the default URLConf for this application, which
                # imports this file.
                success_url = success_url or reverse('invitation_complete')
                return HttpResponseRedirect(success_url)
    else:
        form = form_class()
    objs = InvitationKey.objects
    invitation = objs.create_invitation(request.user, save=False)
    note = _('--your note will be inserted here--')
    preview_context = invitation.get_context({'sender_note': note})
    extra_context.update({
        'form': form,
        'remaining_invitations': remaining_invitations,
        'email_preview': render_to_string('invitation/invitation_email.html',
                                          preview_context),
    })
    return render(request, template_name, extra_context)


@staff_member_required
def send_bulk_invitations(request, success_url=None):
    # current_site, root_url = utils.get_site(request)
    if request.POST.get('post'):
        to_emails = [(e.split(',')[0].strip(), e.split(',')[1].strip() or None,
                      e.split(',')[2].strip() or None) if e.find(',') + 1 else
                     (e.strip() or None, None, None)
                     for e in request.POST['to_emails'].split(';')]

        sender_note = request.POST['sender_note']
        from_email = request.POST['from_email']
        if len(to_emails) > 0 and to_emails[0] != '':
            for recipient in to_emails:
                if recipient[0]:
                    objs = InvitationKey.objects
                    invitation = objs.create_invitation(request.user,
                                                        {models.KEY_EMAIL: recipient})
                    try:
                        invitation.send_to(from_email, mark_safe(sender_note))
                    except:
                        messages.error(request, "Mail to %s failed" %
                                       recipient[0])
            messages.success(request, _("Mail sent successfully"))
            success_url = success_url or reverse('invitation_invite_bulk')
            return HttpResponseRedirect(success_url)
        else:
            err = _('You did not provide any email addresses.')
            messages.error(request, err)
            return HttpResponseRedirect(reverse('invitation_invite_bulk'))
    else:
        invitation = InvitationKey.objects.create_invitation(request.user,
                                                             save=False)
        note = _('--your note will be inserted here--')
        preview_context = invitation.get_context({'sender_note': note})

        html_template = 'invitation/invitation_email.html'
        text_template = 'invitation/invitation_email.txt'
        context = {
            'title': "Send Bulk Invitations",
            'html_preview': render_to_string(html_template, preview_context),
            'text_preview': render_to_string(text_template, preview_context),
        }
        return render_to_response('invitation/invitation_form_bulk.html',
                                  context,
                                  context_instance=RequestContext(request))


def token(request, key):
    # This view should only be called if INVITATION_USE_TOKEN is True so we
    # assume that here
    generator_class = utils.get_token_generator_class()
    generator = generator_class()
    return generator.token_view(request, key)
