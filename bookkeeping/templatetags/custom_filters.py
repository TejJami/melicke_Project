from django import template

register = template.Library()

@register.filter
def format_german_number(value):
    """
    Convert a float to a German-style number format:
    - Uses '.' as a thousand separator
    - Uses ',' as a decimal separator
    """
    try:
        return "{:,.2f}".format(float(value)).replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value

@register.filter
def model_name(obj):
    return obj.__class__.__name__.lower()
