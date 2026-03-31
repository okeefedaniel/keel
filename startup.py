"""Temporary startup script — reset admin password via RESET_ADMIN_PASSWORD env var."""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')

import django
django.setup()

reset_pw = os.environ.get('RESET_ADMIN_PASSWORD', '')
if reset_pw:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    email = os.environ.get('RESET_ADMIN_EMAIL', 'dok@dok.net')
    u, created = User.objects.get_or_create(
        email=email,
        defaults={'username': email, 'is_staff': True, 'is_superuser': True, 'is_active': True},
    )
    if not created:
        u.is_staff = True
        u.is_superuser = True
        u.is_active = True
    u.set_password(reset_pw)
    u.save()
    print(f"Admin password reset for {email}", flush=True)
