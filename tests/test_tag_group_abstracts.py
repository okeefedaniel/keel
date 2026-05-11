"""Tests for the suite-wide Tag and Group abstracts.

Pins the field shape for `AbstractTag` and `AbstractGroup` — the primitives
consumers like Beacon (`Contact.tags`/`Contact.groups`) and Yeoman
(`Invitation.tags`) depend on. Consistent with the abstract-model testing
pattern in test_project_lifecycle_abstracts.py: introspection only, no
concrete subclasses needed.
"""
from django.conf import settings
from django.db import models

from keel.core.models import AbstractGroup, AbstractTag


def _field(model, name):
    return model._meta.get_field(name)


class TestAbstractTag:
    def test_is_abstract(self):
        assert AbstractTag._meta.abstract is True

    def test_required_fields_present(self):
        for name in ['id', 'name', 'slug', 'description', 'color',
                     'is_system', 'created_at']:
            _field(AbstractTag, name)  # raises if missing

    def test_uuid_primary_key(self):
        pk = _field(AbstractTag, 'id')
        assert isinstance(pk, models.UUIDField)
        assert pk.primary_key is True

    def test_name_is_charfield_100(self):
        f = _field(AbstractTag, 'name')
        assert isinstance(f, models.CharField)
        assert f.max_length == 100

    def test_slug_is_slugfield_120_blank(self):
        f = _field(AbstractTag, 'slug')
        assert isinstance(f, models.SlugField)
        assert f.max_length == 120
        assert f.blank is True

    def test_description_is_textfield_blank(self):
        f = _field(AbstractTag, 'description')
        assert isinstance(f, models.TextField)
        assert f.blank is True

    def test_color_is_charfield_blank(self):
        f = _field(AbstractTag, 'color')
        assert isinstance(f, models.CharField)
        assert f.blank is True

    def test_is_system_defaults_false(self):
        f = _field(AbstractTag, 'is_system')
        assert isinstance(f, models.BooleanField)
        assert f.default is False

    def test_created_at_is_auto_now_add(self):
        f = _field(AbstractTag, 'created_at')
        assert isinstance(f, models.DateTimeField)
        assert f.auto_now_add is True

    def test_name_NOT_unique_on_abstract(self):
        # Uniqueness is subclass-controlled — Beacon's Tag.name is globally
        # unique, but Yeoman's InvitationTag is unique-per-agency. Keep the
        # abstract permissive.
        f = _field(AbstractTag, 'name')
        assert f.unique is False

    def test_ordering_by_name(self):
        assert AbstractTag._meta.ordering == ['name']


class TestAbstractGroup:
    def test_is_abstract(self):
        assert AbstractGroup._meta.abstract is True

    def test_required_fields_present(self):
        for name in ['id', 'name', 'slug', 'description', 'color',
                     'is_system', 'created_by', 'created_at', 'updated_at']:
            _field(AbstractGroup, name)

    def test_uuid_primary_key(self):
        pk = _field(AbstractGroup, 'id')
        assert isinstance(pk, models.UUIDField)
        assert pk.primary_key is True

    def test_is_system_defaults_false(self):
        f = _field(AbstractGroup, 'is_system')
        assert f.default is False

    def test_created_by_is_nullable_set_null(self):
        f = _field(AbstractGroup, 'created_by')
        assert isinstance(f, models.ForeignKey)
        assert f.null is True
        assert f.blank is True
        assert f.remote_field.on_delete is models.SET_NULL
        # Points at AUTH_USER_MODEL — accept either string or resolved
        target = f.remote_field.model
        if isinstance(target, str):
            assert target == settings.AUTH_USER_MODEL
        else:
            assert target._meta.swapped == settings.AUTH_USER_MODEL or \
                target._meta.label == settings.AUTH_USER_MODEL

    def test_created_by_no_reverse_relation(self):
        # related_name='+' so subclassing N times doesn't pollute User's
        # reverse-accessor namespace with conflicting names.
        f = _field(AbstractGroup, 'created_by')
        assert f.remote_field.related_name == '+'

    def test_created_at_auto_now_add(self):
        f = _field(AbstractGroup, 'created_at')
        assert f.auto_now_add is True

    def test_updated_at_auto_now(self):
        f = _field(AbstractGroup, 'updated_at')
        assert f.auto_now is True

    def test_name_NOT_unique_on_abstract(self):
        # Subclass-controlled (Beacon's ContactGroup has unique name+slug;
        # other products may scope uniqueness per-tenant).
        f = _field(AbstractGroup, 'name')
        assert f.unique is False

    def test_slug_NOT_unique_on_abstract(self):
        f = _field(AbstractGroup, 'slug')
        assert f.unique is False
        assert f.blank is True

    def test_ordering_by_name(self):
        assert AbstractGroup._meta.ordering == ['name']
