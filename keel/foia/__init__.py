"""
Keel FOIA Module — Cross-product FOIA compliance infrastructure.

Provides the export pipeline that enables any DockLabs product to submit
records for FOIA review in Admiralty (the standalone FOIA request manager).

Components:
- AbstractFOIAExportItem: Queue model for cross-product record export
- FOIAExportRegistry: Products register exportable record types at startup
- submit_to_foia / bulk_submit_to_foia: Export service functions
- FOIAExportMixin: View mixin for "Export to Admiralty" buttons
- foia_audit management command: CI/CD FOIA readiness check

The full FOIA *workflow* (request intake, scope, search, determination,
response, appeal) lives in Admiralty: github.com/okeefedaniel/admiralty
"""
