"""Shared view plumbing.

The page size lives here so every list screen in the product answers the
same `?per_page=` and starts from the same default, rather than each view
picking a number of its own.
"""

# Sizes a screen offers. The default is deliberately more than a screenful
# so an operator scrolls rather than paging.
PAGE_SIZES = [25, 50, 100, 200]
DEFAULT_PAGE_SIZE = 50


def resolve_page_size(request, default=DEFAULT_PAGE_SIZE):
    """`?per_page=` when it names one of the offered sizes, else `default`.
    A hand-typed value can never ask the database for an unbounded page."""
    try:
        size = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return size if size in PAGE_SIZES else default


class DynamicPageSizeMixin:
    """Makes any ListView honour `?per_page=`, and hands the template the
    sizes to offer so the selector can be rendered the same way
    everywhere."""

    paginate_by = DEFAULT_PAGE_SIZE
    page_sizes = PAGE_SIZES

    def get_paginate_by(self, queryset):
        return resolve_page_size(self.request, self.paginate_by)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_sizes"] = self.page_sizes
        ctx["per_page"] = self.get_paginate_by(None)
        return ctx
