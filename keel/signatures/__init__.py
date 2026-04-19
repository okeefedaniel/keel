"""Placeholder for future keel.signatures extraction.

The Harbor and Manifest ``signatures/`` apps are ~2,200 LOC each with
byte-identical ``services.py`` and 12-line-diff ``views.py``. This is the
largest dedup opportunity in the suite, but the extraction is NOT a
drop-in move — it is blocked by three real constraints:

1. **Migration history.** Both products have their own
   ``signatures/migrations/0001_initial.py`` under the ``signatures`` app
   label. Moving models under ``keel.signatures`` changes the label to
   ``keel_signatures``, which Django treats as a brand-new app. Without a
   migration strategy (rename-via-SeparateDatabaseAndState + data-preserving
   ALTER TABLE), the first production deploy would drop signing packets.

2. **Product-local divergence.** ``compat.py`` differs in both products.
   Manifest also ships ``helm_feed.py`` and a ``management/`` package that
   Harbor doesn't have. The services import paths for notifications
   differ (``core.notifications`` vs ``keel.core.notifications``). Any
   extraction must preserve these as adapter seams.

3. **Test coverage.** Neither product has a test for the signing flow.
   Moving 2,200 LOC of workflow orchestration without tests is a
   regression waiting to happen.

**Recommended extraction strategy (to be executed in a dedicated PR):**

a. Keep ``signatures`` as the Django app label in both products.
b. Move ``services.py`` verbatim to ``keel.signatures.services`` and
   re-export from each product's ``signatures/services.py`` as:

       from keel.signatures.services import *  # noqa: F401, F403

c. Normalise ``compat.py`` to a single implementation with both
   notification backends behind a ``KEEL_SIGNATURES_NOTIFY_BACKEND``
   setting. Keep product-local ``compat.py`` as a 2-line re-export.
d. Add pytest coverage for: packet initiation, step transition, signer
   notification, completion, cancellation. Run against both products'
   settings.
e. Only THEN migrate the models — via ``SeparateDatabaseAndState`` +
   ``AlterModelTable`` so the underlying tables keep their names.

This file exists so that future readers know the package is **reserved**
and to prevent a partial extraction from shipping under the same name.
"""

__all__ = []
