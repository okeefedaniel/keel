"""Notification signal handlers.

Currently houses the SMS opt-in confirmation hook: when a user toggles the
SMS channel on for any notification type for the first time, fire a one-time
confirmation SMS so the platform behavior matches the opt-in flow we
declared to The Campaign Registry (TCR) for Twilio A2P 10DLC compliance.

Wiring:
    KeelNotificationsConfig.ready() calls connect_notification_signals()
    after Django has loaded all models. We bind to whichever concrete
    NotificationPreference subclass the product configured via
    settings.KEEL_NOTIFICATION_PREFERENCE_MODEL.
"""
import logging

from django.apps import apps
from django.conf import settings
from django.db.models.signals import post_save, pre_save

logger = logging.getLogger(__name__)

# Sent verbatim — TCR-canonical opt-in confirmation. Stays under 160 chars
# so it ships as a single SMS segment.
CONFIRMATION_BODY = (
    "DockLabs: You're subscribed to admin notifications. "
    'Msg frequency varies. Msg & data rates may apply. '
    'Reply HELP for help, STOP to cancel.'
)

# Stash the pre-save state on the instance so post_save can detect a
# False -> True transition on channel_sms. Using an instance attribute
# avoids any global state and survives concurrent requests fine because
# the same Python object is the only thing that sees both signals.
_PRE_SAVE_FLAG = '_keel_was_sms_enabled_before_save'


def _on_pref_pre_save(sender, instance, **kwargs):
    """Capture the pre-save channel_sms value on the instance."""
    if instance.pk:
        try:
            existing = sender.objects.only('channel_sms').get(pk=instance.pk)
            setattr(instance, _PRE_SAVE_FLAG, bool(existing.channel_sms))
        except sender.DoesNotExist:
            setattr(instance, _PRE_SAVE_FLAG, False)
    else:
        # New row — there was no prior state, so any True is a transition.
        setattr(instance, _PRE_SAVE_FLAG, False)


def _on_pref_post_save(sender, instance, created, **kwargs):
    """Fire the confirmation SMS on the first False -> True transition.

    Conditions, all required:
      1. channel_sms is now True.
      2. channel_sms was False (or non-existent) before this save.
      3. The user has a phone number set.
      4. The user has not already received an SMS opt-in confirmation
         (checked against KEEL_NOTIFICATION_LOG_MODEL — if logging is
         not configured, we err on the side of NOT sending to avoid
         duplicates on re-toggle).
    """
    if not instance.channel_sms:
        return  # Toggle off or save-without-change.

    was_enabled = getattr(instance, _PRE_SAVE_FLAG, False)
    if was_enabled:
        return  # Already on — nothing to confirm.

    user = instance.user
    phone = (getattr(user, 'phone', None) or '').strip()
    if not phone:
        return  # No phone, nothing to send. If they add one later and
                # re-toggle, we'll get another shot.

    if _user_already_confirmed(user):
        return  # Sent already. Don't spam on every re-toggle.

    # Use the dispatch framework so we get the same error handling,
    # logging, and channel-routing as every other SMS in the system.
    try:
        from .dispatch import notify
        notify(
            event='sms_opt_in_confirmation',
            recipients=[user],
            message=CONFIRMATION_BODY,
            title='SMS confirmation',
            channels=['sms'],
            force=True,  # User just opted in — don't re-check preferences.
        )
    except Exception:
        # Never let a confirmation-SMS failure break a preference save.
        logger.exception(
            'sms_opt_in_confirmation: failed to dispatch for user %s',
            getattr(user, 'pk', '?'),
        )


def _user_already_confirmed(user):
    """Has this user already received an SMS opt-in confirmation?

    Conservative: returns True (skip-send) when we can't tell — better
    to miss a re-confirmation than to spam.
    """
    log_path = getattr(settings, 'KEEL_NOTIFICATION_LOG_MODEL', None)
    if not log_path:
        # No log model = no way to dedupe. Skip to avoid spam.
        return True

    try:
        LogModel = apps.get_model(log_path)
        return LogModel.objects.filter(
            recipient=user,
            notification_type='sms_opt_in_confirmation',
            success=True,
        ).exists()
    except Exception:
        # Log model misconfigured or DB error — same conservative default.
        logger.debug(
            'sms_opt_in_confirmation: idempotency check failed, skipping send',
            exc_info=True,
        )
        return True


def connect_notification_signals():
    """Bind pre_save + post_save handlers to the product's preference model.

    Called from KeelNotificationsConfig.ready() after Django finishes
    loading all apps. Safe to call when KEEL_NOTIFICATION_PREFERENCE_MODEL
    is unset (handler simply doesn't bind — no SMS confirmation feature
    on that deployment).
    """
    pref_path = getattr(settings, 'KEEL_NOTIFICATION_PREFERENCE_MODEL', None)
    if not pref_path:
        return

    try:
        PrefModel = apps.get_model(pref_path)
    except (LookupError, ValueError):
        logger.warning(
            'sms_opt_in_confirmation: KEEL_NOTIFICATION_PREFERENCE_MODEL=%r '
            'could not be resolved; signals not connected',
            pref_path,
        )
        return

    pre_save.connect(
        _on_pref_pre_save,
        sender=PrefModel,
        dispatch_uid=f'keel_sms_opt_in_pre_save_{pref_path}',
    )
    post_save.connect(
        _on_pref_post_save,
        sender=PrefModel,
        dispatch_uid=f'keel_sms_opt_in_post_save_{pref_path}',
    )
    logger.debug('sms_opt_in_confirmation: signals connected on %s', pref_path)
