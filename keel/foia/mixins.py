"""FOIA view mixins — drop-in FOIA export support for product views.

Usage in a product's DetailView:

    from keel.foia.mixins import FOIAExportMixin

    class TestimonyDetailView(FOIAExportMixin, DetailView):
        model = Testimony
        foia_record_type = 'testimony'
        foia_product_name = 'lookout'

The mixin adds the ``{% foia_export_button %}`` context automatically.
No template changes needed beyond loading the tag.
"""


class FOIAExportMixin:
    """Add FOIA export button context to any detail view.

    Attributes:
        foia_record_type: The record type string (e.g., 'testimony', 'interaction').
        foia_product_name: The product name (e.g., 'lookout', 'beacon').
    """

    foia_record_type = ''
    foia_product_name = ''

    def get_foia_record_type(self):
        return self.foia_record_type

    def get_foia_product_name(self):
        return self.foia_product_name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['foia_record_type'] = self.get_foia_record_type()
        context['foia_product_name'] = self.get_foia_product_name()
        return context


class FOIAExportListMixin:
    """Add FOIA bulk-export context to any list view.

    Products can add a "Select All / Export Selected to FOIA" action
    to list views by mixing this in.

    Attributes:
        foia_record_type: The record type string.
        foia_product_name: The product name.
    """

    foia_record_type = ''
    foia_product_name = ''

    def get_foia_record_type(self):
        return self.foia_record_type

    def get_foia_product_name(self):
        return self.foia_product_name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['foia_record_type'] = self.get_foia_record_type()
        context['foia_product_name'] = self.get_foia_product_name()
        context['foia_bulk_export'] = True
        return context
