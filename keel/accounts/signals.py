"""Signal handlers for keel.accounts.

Wired in ``KeelAccountsConfig.ready()``.
"""
import logging

from django.db.models.signals import pre_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(pre_delete, sender='keel_accounts.KeelUser')
def delete_avatar_on_user_delete(sender, instance, **kwargs):
    """Remove the user's avatar from object storage before the row is deleted.

    Without this, hard-deleting a KeelUser leaves an orphaned object
    in the avatars S3 bucket forever — minor cost issue but a bigger
    privacy concern when the user expected their data to be gone.

    Best-effort: if the storage call fails (transient S3 error, missing
    file, IAM revoked), we log and let the user delete proceed. The
    DB row going away is the contract; the file is auxiliary.
    """
    avatar = getattr(instance, 'avatar', None)
    if not avatar:
        return
    name = getattr(avatar, 'name', None)
    if not name:
        return
    try:
        avatar.storage.delete(name)
        logger.info(
            'delete_avatar_on_user_delete: user=%s removed key=%s',
            instance.pk, name,
        )
    except Exception:
        logger.warning(
            'delete_avatar_on_user_delete: failed to remove key=%s for user=%s',
            name, instance.pk, exc_info=True,
        )
