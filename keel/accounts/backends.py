"""Authentication backend that accepts either a username or an email address.

Django's default ``ModelBackend`` only authenticates by ``USERNAME_FIELD``.
The shared :class:`keel.accounts.forms.LoginForm` advertises the input as
"Username or email" — without this backend installed, the email branch
silently fails and users see "Please enter a correct username and password"
when they enter their email.

Wire it suite-wide. On Keel (which does not ship allauth) this is the only
backend that resolves email logins. On products that already register
``allauth.account.auth_backends.AuthenticationBackend``, this backend runs
first and resolves the common case without any allauth round-trip — keeping
the contract identical regardless of which auth stack a service uses.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class UsernameOrEmailBackend(ModelBackend):
    """Resolve ``username`` credential against either the username or email column.

    Username match wins when both could match (e.g. an attacker's account whose
    email equals another user's username — we never want the email match to
    silently shadow a real username login).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if not username or password is None:
            return None
        User = get_user_model()
        candidate = User.objects.filter(username__iexact=username).first()
        if candidate is None:
            candidate = User.objects.filter(email__iexact=username).first()
        if candidate is None:
            # Mirror ModelBackend's timing-attack mitigation on miss.
            User().set_password(password)
            return None
        if candidate.check_password(password) and self.user_can_authenticate(candidate):
            return candidate
        return None
