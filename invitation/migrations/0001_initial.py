# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InvitationKey',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, primary_key=True, auto_created=True)),
                ('key', models.CharField(verbose_name='invitation key', db_index=True, max_length=40)),
                ('date_invited', models.DateTimeField(verbose_name='date invited', auto_now_add=True)),
                ('uses_left', models.IntegerField(default=1)),
                ('duration', models.IntegerField(null=True, default=7, blank=True)),
                ('recipient_email', models.EmailField(default='', max_length=254, blank=True)),
                ('recipient_first_name', models.CharField(default='', max_length=24, blank=True)),
                ('recipient_last_name', models.CharField(default='', max_length=24, blank=True)),
                ('recipient_phone_number', models.CharField(max_length=15, blank=True)),
                ('recipient_other', models.CharField(default='', max_length=255, blank=True)),
                ('from_user', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name='invitations_sent')),
                ('registrant', models.ManyToManyField(null=True, to=settings.AUTH_USER_MODEL, related_name='invitations_used', blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='InvitationUser',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, primary_key=True, auto_created=True)),
                ('invites_allocated', models.IntegerField(default=3)),
                ('invites_accepted', models.IntegerField(default=0)),
                ('inviter', models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
