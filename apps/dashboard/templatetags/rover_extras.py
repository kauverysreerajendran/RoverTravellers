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
def sno(page_obj, counter0, offset=0):
    """The continuous S.No of a table row.

    Numbering runs across pages, so page 2 of a 25-row table starts at 26,
    and `offset` carries any rows rendered above the paginated ones (the
    incoming rows at the top of a process Main Table). Presentation only:
    S.No is never stored, sorted on or searched.
    """
    try:
        offset = int(offset or 0)
        counter0 = int(counter0 or 0)
    except (TypeError, ValueError):
        return ""
    # Templates without pagination pass no page_obj at all; numbering then
    # simply starts at 1.
    start_index = getattr(page_obj, "start_index", None)
    start = start_index() if callable(start_index) else 1
    return offset + start + counter0


@register.simple_tag
def url_with_pk(url_name, pk):
    from django.urls import reverse

    if not url_name:
        return "#"
    return reverse(url_name, kwargs={"pk": pk})
