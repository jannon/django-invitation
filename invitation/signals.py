from django.dispatch import Signal

invite_invited = Signal(providing_args=["invite_key"])
invite_accepted = Signal(providing_args=["invite_key"])
# TODO: trigger this signal
invite_joined_independently = Signal(providing_args=["invite_key"])
