"""Form widget for the mention-aware textarea.

Drop in as the widget on any ``content`` field whose form inherits
``MentionFormMixin``. Renders a normal Bootstrap-styled textarea plus a
``data-mentions-search-url`` attribute that the JS picker reads.
"""
from __future__ import annotations

import logging

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, reverse_lazy

logger = logging.getLogger(__name__)


class MentionableTextarea(forms.Textarea):
    """Textarea that wires up the @-mention autocomplete picker.

    Adds the ``mentionable`` CSS class plus a ``data-mentions-search-url``
    attribute so the static JS in ``keel/mentions/static/keel/mentions/``
    can find the autocomplete endpoint.
    """

    class Media:
        css = {'all': ('keel/mentions/mentions.css',)}
        js = ('keel/mentions/mentions.js',)

    def __init__(self, *args, search_url=None, **kwargs):
        attrs = kwargs.pop('attrs', None) or {}
        if search_url is None:
            search_url = reverse_lazy('keel_mentions:mentions_search')
        self._search_url = search_url

        existing_class = attrs.get('class', '')
        attrs['class'] = (existing_class + ' form-control mentionable').strip()
        attrs.setdefault(
            'placeholder',
            'Add a note — type @ to mention a teammate',
        )
        attrs['data-mentions-search-url'] = ''  # set lazily in build_attrs
        attrs.setdefault('aria-autocomplete', 'list')
        attrs.setdefault('autocomplete', 'off')

        super().__init__(attrs=attrs, *args, **kwargs)

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        # Resolve the lazy URL now so the rendered HTML has the real path.
        try:
            attrs['data-mentions-search-url'] = str(self._search_url)
        except NoReverseMatch as exc:
            raise ImproperlyConfigured(
                "MentionableTextarea: the URL name "
                "'keel_mentions:mentions_search' could not be reversed. "
                "Did you include('keel.mentions.urls') in your product's urls.py?"
            ) from exc
        return attrs
