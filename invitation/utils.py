import datetime
from hashlib import sha1 as sha_constructor
import importlib
import random

from django.conf import settings
from django.contrib.sites.models import Site
from django.contrib.sites.requests import RequestSite
from django.core.files.storage import default_storage
from django.core.urlresolvers import reverse


def get_site(request=None):
    site = None
    root_url = 'http://localhost'
    if Site._meta.installed:
        site = Site.objects.get_current()
        root_url = 'http://%s' % site.domain
    else:
        if request:
            site = RequestSite(request)
    return site, root_url


def get_registration_backend_class(backend_str=None):
    return str_to_class(backend_str, 'INVITATION_BACKEND',
                        'invitation.backends.AllAuthRegistrationBackend')


def get_delivery_backend_class(delivery_str=None):
    return str_to_class(delivery_str, 'INVITATION_DELIVERY_BACKEND',
                        'invitation.backends.EmailDeliveryBackend')


def get_invitation_form(form_str=None):
    return str_to_class(form_str, 'INVITATION_FORM',
                        'invitation.forms.DefaultInvitationKeyForm')


def get_token_generator_class(generator_str=None):
    return str_to_class(generator_str, 'INVITATION_TOKEN_GENERATOR',
                        'invitation.utils.DefaultTokenGenerator')


def str_to_class(class_str, settings_key="", default_str=""):
    class_str = class_str or getattr(settings, settings_key, default_str)
    mod, _, kls = class_str.rpartition('.')
    return class_for_name(mod, kls)


def class_for_name(module_name, class_name):
    try:
        m = importlib.import_module(module_name)
        c = getattr(m, class_name)
        return c
    except:
        return None


def get_invitation_key(user):
    salt = sha_constructor(str(random.random()).encode()).hexdigest()[:5]
    nowish = datetime.datetime.now()
    user_str = user.get_username()
    key_str = "%s%s%s" % (nowish, salt, user_str)
    key = sha_constructor(key_str.encode()).hexdigest()
    return key


class BaseTokenGenerator():
    def generate_token(self, instance, invitation_url):
        raise NotImplementedError("Create a subclass and implement method")

    def token_view(self, request, instance):
        raise NotImplementedError("Create a subclass and implement method")

    def handle_invitation_delete(self, instance):
        raise NotImplementedError("Create a subclass and implement method")

    def handle_invitation_used(self, instance):
        raise NotImplementedError("Create a subclass and implement method")


class DefaultTokenGenerator(BaseTokenGenerator):
    def generate_token(self, instance, invitation_url):
        # token imports
        from PIL import Image, ImageFont, ImageDraw
        from django.core.files.temp import NamedTemporaryFile
        from django.core.files import File
        import urllib2
        from urlparse import urlparse, urlunparse

        _, root_url = get_site()

        def stamp(image, text, offset):
                f = ImageFont.load_default()
                txt_img = Image.new('RGBA', f.getsize(text))
                d = ImageDraw.Draw(txt_img)
                d.text((0, 0), text, font=f, fill="#888")
                exp_img_r = txt_img.rotate(0, expand=1)
                iw, ih = image.size
                tw, th = txt_img.size
                x = iw / 2 - tw / 2
                y = ih / 2 - th / 2
                image.paste(exp_img_r, (x, y + offset), exp_img_r)
                return offset + th

        # normalize sataic url
        r_parse = urlparse(root_url, 'http')
        s_parse = urlparse(settings.STATIC_URL, 'http')
        s_parts = (s_parse.scheme, s_parse.netloc or r_parse.netloc,
                   s_parse.path, s_parse.params, s_parse.query,
                   s_parse.fragment)
        static_url = urlunparse(s_parts)

        # open base token image
        img_url = static_url + 'notification/img/token-invite.png'
        temp_img = NamedTemporaryFile()
        temp_img.write(urllib2.urlopen(img_url).read())
        temp_img.flush()
        image = Image.open(temp_img.name)

        # stamp expiration date
        delta = datetime.timedelta(days=settings.ACCOUNT_INVITATION_DAYS)
        expiration_date = instance.date_invited + delta
        exp_text = expiration_date.strftime("%x")
        stamp(image, exp_text, 18)

        # stamp recipient name
        if instance.recipient[1]:
            offset = stamp(image, instance.recipient[1], -16)
        if instance.recipient[2]:
            offset = stamp(image, instance.recipient[2], offset)
        image.save(temp_img.name, "PNG", quality=95)
        if not default_storage.exists('tokens/%s.png' % instance.key):
            default_storage.save('tokens/%s.png' % instance.key,
                                 File(temp_img))
        get_token_url = root_url + reverse('invitation_token',
                                           kwargs={'key': instance.key})
        token_html = ''.join(['<a style="display: inline-block;" href="',
                              invitation_url,
                              '"><img width="100" height="100" class="token"',
                              ' src="',
                              get_token_url,
                              '" alt="invitation token"></a>'])
        return token_html

    def token_view(self, request, key):
        '''
        Returns an aproproate token image.  If the key is valid & token image
        exist, a personalized token is returned or else a token image marked
        invalid is returned.
        '''
        import urllib2
        import mimetypes
        from django.http import HttpResponse
        from urlparse import urlparse, urlunparse
        from invitation.models import InvitationKey

        print ('---token')
        site = get_site(request)
        scheme = 'http'
        if request.is_secure():
            scheme = 'https'
        root_url = '%s://%s' % (scheme, site.domain)
        r_parse = urlparse(root_url, scheme)
        s_parse = urlparse(settings.STATIC_URL, scheme)
        m_parse = urlparse(settings.MEDIA_URL, scheme)
        s_parts = (s_parse.scheme, s_parse.netloc or r_parse.netloc,
                   s_parse.path, s_parse.params, s_parse.query,
                   s_parse.fragment)
        static_url = urlunparse(s_parts)
        m_parts = (m_parse.scheme, m_parse.netloc or r_parse.netloc,
                   m_parse.path, m_parse.params, m_parse.query,
                   m_parse.fragment)
        media_url = urlunparse(m_parts)
        print ('static_url', static_url)
        print ('media_url', media_url)

        token_url = '%stokens/%s.png' % (media_url, key)
        print (token_url)
        token_invalid_url = '%snotification/img/%s.png' % (static_url,
                                                           'token-invalid')
        token_path = 'tokens/%s.png' % key
        is_key_valid = InvitationKey.objects.is_key_valid
        valid_key = is_key_valid(key) or key == 'previewkey00000000'
        if default_storage.exists(token_path) and valid_key:
            contents = urllib2.urlopen(token_url).read()
            mimetype = mimetypes.guess_type(token_url)
            response = HttpResponse(contents, mimetype=mimetype)
        else:
            contents = urllib2.urlopen(token_invalid_url).read()
            mimetype = mimetypes.guess_type(token_invalid_url)
            response = HttpResponse(contents, mimetype=mimetype)

        return response

    def handle_invitation_delete(self, instance):
        """Delete token image."""
        try:
            default_storage.delete('tokens/%s.png' % instance.key)
        except:
            pass

    def handle_invitation_used(self, instance):
        default_storage.delete('tokens/%s.png' % instance.key)
