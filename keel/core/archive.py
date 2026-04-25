"""Suite-wide archive primitive.

Pairs with the existing ``AbstractArchivedRecord`` (keel.core.models):

- ``ArchivableMixin`` sets ``archived_at`` on the LIVE row for fast filtering.
- ``AbstractArchivedRecord`` (subclassed per product) carries the retention
  policy and feeds ``purge_expired_archives``.

Consumers MUST add an ``archived`` terminal status to their workflow that is
reachable from at least the natural ``done`` states. Unarchiving routes to
``self.previous_terminal_status`` if the consumer model defines that field
(see Helm's Project), otherwise to ``ARCHIVE_RESTORE_STATUS`` (default
``'active'``).

The mixin intentionally does NOT define ``archive()`` / ``unarchive()``
methods. Those live in each consumer's service layer so the consumer can
transactionally write the retention row, audit log, and notifications atomic
with the status change.
"""
from django.db import models
from django.views.generic import ListView


class ArchivableMixin(models.Model):
    """Adds an ``archived_at`` timestamp to any ``WorkflowModelMixin`` model.

    A ``True`` value of ``is_archived`` should always agree with
    ``status == 'archived'`` — consumers are responsible for keeping the
    two in sync via their service layer.
    """

    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: Status the consumer's ``unarchive_*`` service should restore to when
    #: the model does not track ``previous_terminal_status``.
    ARCHIVE_RESTORE_STATUS = 'active'

    class Meta:
        abstract = True

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class ArchiveQuerySetMixin:
    """Drop-in helpers for archivable model querysets.

    Usage::

        class ProjectQuerySet(ArchiveQuerySetMixin, models.QuerySet):
            ...

        class Project(..., ArchivableMixin):
            objects = ProjectQuerySet.as_manager()

        Project.objects.active()    # archived_at IS NULL
        Project.objects.archived()  # archived_at IS NOT NULL, newest first
    """

    def active(self):
        return self.filter(archived_at__isnull=True)

    def archived(self):
        return self.filter(archived_at__isnull=False).order_by('-archived_at')


class ArchiveListView(ListView):
    """Generic archived-items list view.

    Usage::

        class ArchivedProjectsView(ArchiveListView):
            model = Project
            template_name = 'tasks/archived_projects.html'
            archive_label = 'Projects'

    The default queryset returns only archived rows ordered by
    ``archived_at`` desc. Subclasses commonly override ``get_queryset`` to
    additionally filter by per-user ACL.
    """

    paginate_by = 25
    archive_label = ''

    def get_queryset(self):
        return self.model._default_manager.filter(
            archived_at__isnull=False,
        ).order_by('-archived_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['archive_label'] = (
            self.archive_label or self.model._meta.verbose_name_plural
        )
        return ctx
