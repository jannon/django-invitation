from django.contrib import admin
from invitation.models import InvitationKey, InvitationUser

class InvitationKeyAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'from_user', 'recipient', 'date_invited', 'uses_left', 'key_expired', 'expiry_date' )
    filter_horizontal = ('registrant',)
    readonly_fields = ('registrant',)

class InvitationUserAdmin(admin.ModelAdmin):
    list_display = ('inviter', 'invites_remaining')

admin.site.register(InvitationKey, InvitationKeyAdmin)
admin.site.register(InvitationUser, InvitationUserAdmin)
