import datetime
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now
from django.core.urlresolvers import reverse
from django.db import connection

from invitation import utils
from invitation.signals import (invite_invited, invite_accepted)


token_generator = None
if getattr(settings, 'INVITATION_USE_TOKEN', False):
    generator_class = utils.get_token_generator_class()
    token_generator = generator_class()

KEY_EMAIL = "recipient_email"
KEY_FNAME = "recipient_first_name"
KEY_LNAME = "recipient_last_name"
KEY_OTHER = "recipient_other"
KEY_GROUPS = "groups"


class InvitationKeyManager(models.Manager):
    def get_key(self, invitation_key):
        """
        Return InvitationKey, or None if it doesn't (or shouldn't) exist.
        """
        try:
            key = self.get(key=invitation_key)
        except self.model.DoesNotExist:
            return None

        return key

    def is_key_valid(self, invitation_key):
        """
        Check if an ``InvitationKey`` is valid or not, returning a valid key
        or false.
        """
        invitation_key = self.get_key(invitation_key)
        if invitation_key and invitation_key.is_usable():
            return invitation_key
        return False

    def create_invitation(self, user, recipient_dict={
        KEY_EMAIL: 'recipient@email.com',
        KEY_FNAME: 'Firstname',
        KEY_LNAME: 'Lastname',
    }, save=True):
        """
        Create an ``InvitationKey`` and returns it.

        The key for the ``InvitationKey`` is generated by the function
        references byt settings.INVITATION_KEY_GENERATOR.  The default
        implementation will be a SHA1 hash, generated from a combination of the
        ``User``'s get_username() and a random salt.
        """
        generate_key = getattr(settings, 'INVITATION_KEY_GENERATOR',
                               utils.get_invitation_key)
        key = generate_key(user)
        if not save:
            return InvitationKey(from_user=user, key='previewkey00000000',
                                 date_invited=datetime.datetime.now(),
                                 **recipient_dict)
        return self.create(from_user=user, key=key, **recipient_dict)

    # TODO: probably something different with 'recipient'
    def create_bulk_invitation(self, user, key, uses, recipient):
        """ Create a set of invitation keys - these can be used by anyone, not
        just a specific recipient """
        return self.create(from_user=user, key=key, uses_left=uses,
                           recipient=None)

    def remaining_invitations_for_user(self, user):
        """
        Return the number of remaining invitations for a given ``User``.
        """
        invitation_user, _ = InvitationUser.objects.get_or_create(
            inviter=user,
            defaults={'invitations_allocated': settings.INVITATIONS_PER_USER})
        return invitation_user.invites_remaining()

    def delete_expired_keys(self):
        for key in self.all():
            if key.key_expired():
                key.delete()


class InvitationKey(models.Model):
    key = models.CharField(_('invitation key'), max_length=40, db_index=True)
    date_invited = models.DateTimeField(_('date invited'),
                                        auto_now_add=True)
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL,
                                  related_name='invitations_sent')
    registrant = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                        blank=True,
                                        related_name='invitations_used')
    uses_left = models.IntegerField(default=1)

    # -1 duration means the key won't expire
    duration = models.IntegerField(default=settings.ACCOUNT_INVITATION_DAYS,
                                   null=True, blank=True)

    objects = InvitationKeyManager()

    recipient_email = models.EmailField(max_length=254, default="", blank=True)
    recipient_first_name = models.CharField(max_length=24, default="",
                                            blank=True)
    recipient_last_name = models.CharField(max_length=24, default="",
                                           blank=True)
    recipient_other = models.CharField(max_length=255, default="", blank=True)

    groups = models.TextField(default="", blank=True)

    def __str__(self):
        from_user = self.from_user.get_username()
        return "Invitation from %s on %s (%s)" % (from_user, self.date_invited,
                                                  self.key)

    def is_usable(self):
        """
        Return whether this key is still valid for registering a new user.
        """
        return self.uses_left > 0 and not self.key_expired()

    def _expiry_date(self):
        # Assumes the duration is positive
        assert self.duration > -1
        expiration_duration = self.duration or settings.ACCOUNT_INVITATION_DAYS
        expiration_date = datetime.timedelta(days=expiration_duration)
        return self.date_invited + expiration_date

    def key_expired(self):
        """
        Determine whether this ``InvitationKey`` has expired, returning
        a boolean -- ``True`` if the key has expired.

        The date the key has been created is incremented by the number of days
        specified in the setting ``ACCOUNT_INVITATION_DAYS`` (which should be
        the number of days after invite during which a user is allowed to
        create their account); if the result is less than or equal to the
        current date, the key has expired and this method returns ``True``.

        """
        if self.duration < 0:
            return False
        return self._expiry_date() <= now()
    key_expired.boolean = True

    def expiry_date(self):
        if self.duration < 0:
            return _('never')
        return self._expiry_date().strftime('%d %b %Y %H:%M')
    expiry_date.short_description = _('Expiry date')

    def mark_used(self, registrant):
        """
        Note that this key has been used to register a new user.
        """
        self.uses_left -= 1
        self.registrant.add(registrant)
        if token_generator:
            token_generator.handle_invitation_used(self)
        invite_accepted.send(sender=InvitationKey, invite_key=self)
        self.from_user.invitationuser.increment_accepted()
        self.save()

    def group_user(self, registrant):
        """
        Add the user to any groups that have been stashed in the key
        """
        if self.groups is not None:
            groups_qs = Group.objects.filter(name__in=self.groups.split(','))
            group_list = [group for group in groups_qs]
            registrant.groups.add(*group_list)

    def get_context(self, extra_context={}):
        site, root_url = utils.get_site()
        invitation_url = root_url + reverse('invitation_invited',
                                            kwargs={'invitation_key': self.key}
                                            )
        delta = datetime.timedelta(days=settings.ACCOUNT_INVITATION_DAYS)
        exp_date = self.date_invited + delta
        context = {'invitation_key': self,
                   'expiration_days': settings.ACCOUNT_INVITATION_DAYS,
                   'from_user': self.from_user,
                   'site': site,
                   'root_url': root_url,
                   'expiration_date': exp_date,
                   'recipient_email': self.recipient_email,
                   'recipient_first_name': self.recipient_first_name,
                   'recipient_last_name': self.recipient_last_name,
                   'recipient_other': self.recipient_other,
                   'token': self.generate_token(invitation_url),
                   'invitation_url': invitation_url}
        context.update(extra_context)
        return context

    def send_to(self, delivery_backend):
        context = self.get_context()
        delivery_backend.send_invitation(context)
        invite_invited.send(sender=InvitationKey, invite_key=self)

    def generate_token(self, invitation_url):
        if token_generator:
            return token_generator.generate_token(self, invitation_url)

        token_html = ''.join(['<a style="display: inline-block;" href="',
                              invitation_url,
                              '">',
                              invitation_url,
                              '</a>'])
        return token_html

    def recipient(self):
        return self.recipient_email or self.recipient_phone_number or \
            self.recipient_other or ""


class InvitationUser(models.Model):
    inviter = models.OneToOneField(settings.AUTH_USER_MODEL, unique=True)
    invites_allocated = \
        models.IntegerField(default=settings.INVITATIONS_PER_USER)
    invites_accepted = models.IntegerField(default=0)

    def __str__(self):
        return "InvitationUser for %s" % self.inviter.get_username()

    def increment_accepted(self):
        self.invites_accepted += 1
        self.save()

    @classmethod
    def add_invites_to_user(cls, user, num_invites):
        invite_user, _ = InvitationUser.objects.get_or_create(user=user)
        if invite_user.invites_allocated != -1:
            invite_user.invites_allocated += num_invites
            invite_user.save()

    @classmethod
    def add_invites(cls, num_invites):
        for user in get_user_model().objects.all():
            cls.add_invites(user, num_invites)

    @classmethod
    def topoff_user(cls, user, num_invites):
        "Makes sure user has a certain number of invites"
        invite_user, _ = cls.objects.get_or_create(user=user)
        remaining = invite_user.invites_remaining()
        if remaining != -1 and remaining < num_invites:
            invite_user.invites_allocated += (num_invites - remaining)
            invite_user.save()

    @classmethod
    def topoff(cls, num_invites):
        "Makes sure all users have a certain number of invites"
        for user in get_user_model().objects.all():
            cls.topoff_user(user, num_invites)

    def invites_remaining(self):
        if self.invites_allocated == -1:
            return -1
        return self.invites_allocated - self.invites_sent()

    def invites_sent(self):
        return self.inviter.invitations_sent.count()

    def can_send(self):
        if self.invites_allocated == -1:
            return True
        return self.invites_allocated > self.invites_sent()
    can_send.boolean = True


# TODO: check to see if there is an outstanding invite for this user
# to see if we need to trigger the independently_joined signal
def user_post_save(sender, instance, created, **kwargs):
    """Create InvitationUser for user when User is created."""
    if created:
        invitation_user = InvitationUser()
        invitation_user.inviter = instance
        invitation_user.invitations_allocated = settings.INVITATIONS_PER_USER
        # prevent error on syncdb when superuser is created
        try:
            invitation_user.save()
        except:
            connection.close()

models.signals.post_save.connect(user_post_save,
                                 sender=settings.AUTH_USER_MODEL)

# def invitation_key_post_save(sender, instance, created, **kwargs):
#     """Decrement invitations_remaining when InvitationKey is created."""
#    objs = InvitationUser.objects
#     if created:
#         invitation_user = objs.get(inviter=instance.from_user)
#         remaining = invitation_user.invitations_remaining
#         invitation_user.invitations_remaining = remaining-1
#         invitation_user.save()

# models.signals.post_save.connect(invitation_key_post_save,
#                                sender=InvitationKey)


def invitation_key_pre_delete(sender, instance, **kwargs):
    if token_generator:
        token_generator.handle_invitation_deleted(instance)

models.signals.post_delete.connect(invitation_key_pre_delete,
                                   sender=InvitationKey)
