"""Hindi translations for the farmer-facing site.

Why a Python catalog rather than gettext
----------------------------------------
The usual Django i18n route is ``{% trans %}`` + a compiled ``django.mo``.
That needs the GNU gettext binaries (``msgfmt``/``xgettext``), which are not
available in this environment, so a gettext catalog cannot be built or refreshed
here. A plain Python mapping is therefore the source of truth: it needs no
external tooling, it is reviewable in a diff, and the very same mapping is
handed to the browser as JSON so JavaScript-rendered strings switch language
too (see ``KS.t()`` in ``static/js/app.js``).

``translate()`` falls back to the English source string, so a missing entry
degrades to readable English rather than to a blank label. Entries are matched
exactly and case-sensitively, because that is what the template tag supplies.

The mapping lives in ``i18n_hi_a`` / ``i18n_hi_b`` because it is large; this
module owns the merge and the lookup.
"""

from django.utils import translation

from apps.core.i18n_hi_a import TRANSLATIONS as _PART_A
from apps.core.i18n_hi_b import TRANSLATIONS as _PART_B
from apps.core.i18n_hi_c import TRANSLATIONS as _PART_C

# Merged in part order. The generator refuses to emit a key twice, so this is a
# plain union and a duplicate could only come from a hand edit.
HI_TRANSLATIONS = {**_PART_A, **_PART_B, **_PART_C}


def translate(text, code=None):
    """Return the Hindi for ``text`` when Hindi is active, else the source.

    ``code`` defaults to the language Django has activated for this request
    (LocaleMiddleware reads it from the cookie the switch view sets), so a
    template never has to know which language it is being rendered in.

    Hindi renders noticeably wider than Latin script, so a missing entry is
    better shown in English than silently blanked.
    """
    if not text:
        return text
    if code is None:
        code = translation.get_language()
    if code != "hi":
        return text
    return HI_TRANSLATIONS.get(text, text)


def catalog_for(code):
    """Translation mapping for ``code``; an empty dict means "no translation"."""
    return HI_TRANSLATIONS if code == "hi" else {}