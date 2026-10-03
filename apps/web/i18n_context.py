"""Expose the active language and the translation catalog to every template.

``ks_i18n_json`` is rendered into ``<script>`` in ``base.html`` so the browser
gets the same dictionary the templates use. Without it the JavaScript layer
would have to carry a second, drifting copy of the Hindi strings.
"""
import json

from django.utils import translation

from apps.core.i18n_text import HI_TRANSLATIONS


def i18n_context(request):
    code = translation.get_language() or "en"
    return {
        "ks_lang": code,
        "ks_i18n_json": json.dumps(HI_TRANSLATIONS if code == "hi" else {}, ensure_ascii=False),
    }