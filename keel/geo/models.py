"""Connecticut municipalities: the suite's shared town reference.

Every product that records where something happened (an award, a company, a
contact's district) points at one of the 169 Connecticut municipalities. Before
this module each product kept its own free-text town column and its own idea of
what "Mystic" or "Dayville" meant.

Two models and one lookup:

* ``Municipality`` — the 169 towns. ``number`` (the state's 1..169 municipality
  number) is the primary key and the ONLY key that may cross a product
  boundary. Each product database holds its own copy of this table, so a
  surrogate key would differ from one database to the next; ``number`` cannot.
  ``slug`` is public-URL material and must never change once shipped.
* ``MunicipalityAlias`` — villages, boroughs and known misspellings that
  resolve to a town ("Dayville" -> Killingly), plus names that straddle more
  than one town ("Mystic" -> Groton/Stonington) which resolve to no town on
  purpose.
* ``Municipality.resolve(text)`` — text in, ``(municipality, reason)`` out.

Rows are loaded by ``manage.py load_ct_municipalities`` from the bundled
fixture. Operators add aliases in the Django admin without a keel release.
"""
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

MULTI_TOWN = 'multi_town'


def normalize(text):
    """Fold a place name for matching: trim, collapse inner whitespace, casefold."""
    return ' '.join(str(text or '').split()).casefold()


class Resolver:
    """In-memory town lookup for bulk work (imports that resolve thousands of rows).

    Built once from two queries; ``Municipality.resolve`` is the same contract
    at two queries per call.
    """

    def __init__(self, municipalities, aliases):
        self._by_name = {normalize(m.name): m for m in municipalities}
        by_number = {m.number: m for m in municipalities}
        self._by_alias = {
            normalize(a.alias): (None if a.multi_town else by_number.get(a.municipality_id), a.multi_town)
            for a in aliases
        }

    def __call__(self, text):
        key = normalize(text)
        if not key:
            return None, None
        town = self._by_name.get(key)
        if town is not None:
            return town, None
        hit = self._by_alias.get(key)
        if hit is None:
            return None, None
        town, multi_town = hit
        return (None, MULTI_TOWN) if multi_town else (town, None)


class MunicipalityQuerySet(models.QuerySet):
    def resolver(self):
        """Return a ``Resolver`` over every municipality and alias (two queries)."""
        return Resolver(list(self.all()), list(MunicipalityAlias.objects.all()))


class Municipality(models.Model):
    """One of Connecticut's 169 municipalities."""

    number = models.PositiveSmallIntegerField(
        primary_key=True,
        help_text=_('State municipality number, 1-169. The only cross-product key.'),
    )
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(
        max_length=100, unique=True,
        help_text=_('Public URL segment. Never change it once shipped.'),
    )
    objectid = models.PositiveIntegerField(
        null=True, blank=True,
        help_text=_('OBJECTID of the town polygon in the CT DOT boundary layer.'),
    )
    county = models.CharField(max_length=50, blank=True)
    planning_region = models.CharField(max_length=100, blank=True)
    council_of_governments = models.CharField(max_length=100, blank=True)
    cog_abbr = models.CharField(max_length=20, blank=True)
    square_miles = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    population = models.PositiveIntegerField(null=True, blank=True)

    objects = MunicipalityQuerySet.as_manager()

    class Meta:
        ordering = ['name']
        verbose_name = _('Municipality')
        verbose_name_plural = _('Municipalities')

    def __str__(self):
        return self.name

    @classmethod
    def resolve(cls, text):
        """Resolve free text to a town.

        Returns ``(municipality, reason)``:

        * ``(m, None)`` — an exact town name or a single-town alias.
        * ``(None, 'multi_town')`` — a name that spans more than one town.
        * ``(None, None)`` — not recognised; the caller decides what that means
          (blank, statewide, out of state, a typo worth adding as an alias).

        Matching ignores case and surrounding / repeated whitespace. For bulk
        work use ``Municipality.objects.resolver()``.
        """
        key = normalize(text)
        if not key:
            return None, None
        town = cls.objects.filter(name__iexact=key).first()
        if town is not None:
            return town, None
        alias = (
            MunicipalityAlias.objects.select_related('municipality')
            .filter(alias__iexact=key).first()
        )
        if alias is None:
            return None, None
        if alias.multi_town:
            return None, MULTI_TOWN
        return alias.municipality, None


class MunicipalityAlias(models.Model):
    """A village, borough or misspelling that stands for a town."""

    class Source(models.TextChoices):
        FIXTURE = 'fixture', _('Bundled fixture')
        ADMIN = 'admin', _('Added by an operator')

    alias = models.CharField(max_length=100, unique=True)
    municipality = models.ForeignKey(
        Municipality, on_delete=models.CASCADE, null=True, blank=True,
        related_name='aliases',
    )
    multi_town = models.BooleanField(
        default=False,
        help_text=_('The name spans more than one town, so it resolves to none.'),
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ADMIN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['alias']
        verbose_name = _('Municipality alias')
        verbose_name_plural = _('Municipality aliases')
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(municipality__isnull=False, multi_town=False)
                    | Q(municipality__isnull=True, multi_town=True)
                ),
                name='keel_geo_alias_town_xor_multi_town',
            ),
        ]

    def __str__(self):
        target = _('multi-town') if self.multi_town else self.municipality
        return f'{self.alias} -> {target}'

    def save(self, *args, **kwargs):
        # Stored trimmed so the unique index and the iexact lookup agree.
        self.alias = ' '.join(str(self.alias or '').split())
        super().save(*args, **kwargs)
