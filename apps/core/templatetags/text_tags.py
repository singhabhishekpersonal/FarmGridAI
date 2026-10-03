from django import template

from apps.core.i18n_text import translate

register = template.Library()


class TranslateNode(template.Node):
    """Render the translation, or assign it when ``as name`` was used."""

    def __init__(self, value, asvar=None):
        self.value = value
        self.asvar = asvar

    def render(self, context):
        out = translate(self.value.resolve(context, ignore_failures=True))
        if self.asvar:
            context[self.asvar] = out
            return ""
        if context.autoescape:
            return template.defaultfilters.escape(out)
        return out


@register.tag(name="t")
def do_t(parser, token):
    """Translate a literal into the language Django has activated.

    ``{% load text_tags %}{% t "Dashboard" %}``

    Falls back to the English source when there is no entry, so an untranslated
    label is still readable rather than blank.

    ``as name`` mirrors Django's own ``{% translate ... as name %}`` and exists
    for the one place a translated value has to be an expression rather than
    output - a filter argument cannot contain another tag::

        {% t "Equipment" as equipment_label %}
        {{ equipment.display_name|default:equipment_label }}
    """
    bits = token.split_contents()
    tag_name, bits = bits[0], bits[1:]

    asvar = None
    if len(bits) >= 2 and bits[-2] == "as":
        asvar = bits[-1]
        bits = bits[:-2]
        if not asvar.isidentifier():
            raise template.TemplateSyntaxError(
                "%r 'as' argument must be a valid identifier, got %r" % (tag_name, asvar)
            )

    if len(bits) != 1:
        raise template.TemplateSyntaxError(
            "%r takes exactly one string, optionally followed by 'as name'" % tag_name
        )

    value = parser.compile_filter(bits[0])
    return TranslateNode(value, asvar)