from django import template

register = template.Library()


@register.filter(name="getattr")
def get_attribute(obj, attr_name):
    if obj is None:
        return ""
    value = getattr(obj, attr_name, "")
    if value is None:
        return ""
    return value


@register.simple_tag
def url_with_pk(url_name, pk):
    from django.urls import reverse

    if not url_name:
        return "#"
    return reverse(url_name, kwargs={"pk": pk})
