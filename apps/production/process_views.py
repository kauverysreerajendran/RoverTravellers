"""Two generic views serve all ten process screens.

`/process/<slug>/main/`     -> ProcessMainTableView
`/process/<slug>/complete/` -> ProcessCompleteTableView

Both read their model, columns, filters and row actions from the process
registry, so neither view nor template knows anything about a specific
process.
"""

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.urls import reverse
from django.views.generic import RedirectView, TemplateView

from .process_registry import PROCESSES, get_process

logger = logging.getLogger(__name__)

PAGE_SIZES = [10, 25, 50, 100]
DEFAULT_PAGE_SIZE = 25


class ProcessTableView(LoginRequiredMixin, TemplateView):
    """Shared plumbing: resolve the process from the URL, apply the
    status/search filters, paginate, and hand the template a list of
    pre-resolved rows so no field mapping is hardcoded in HTML."""

    submenu = ""  # "main" | "complete"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.process = get_process(kwargs.get("process"))
        if self.process is None:
            raise Http404(f"Unknown process '{kwargs.get('process')}'.")

    def page_size(self):
        try:
            size = int(self.request.GET.get("per_page", DEFAULT_PAGE_SIZE))
        except (TypeError, ValueError):
            return DEFAULT_PAGE_SIZE
        return size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE

    def paginate(self, queryset):
        paginator = Paginator(queryset, self.page_size())
        return paginator.get_page(self.request.GET.get("page"))

    def load_rows(self, columns, *, complete):
        """Fetch + render rows, degrading to a visible error state rather
        than a 500 if the query or a column accessor fails."""
        process = self.process
        status = self.request.GET.get("status", "")
        search = self.request.GET.get("q", "").strip()
        try:
            source = process.complete_queryset(self.request) if complete else process.main_queryset(self.request)
            queryset = process.filter_queryset(source, status=status, search=search)
            queryset = process.sort_queryset(
                queryset, columns,
                sort=self.request.GET.get("sort", ""),
                direction=self.request.GET.get("dir", "asc"),
            )
            page = self.paginate(queryset)
            rows = process.build_rows(page.object_list, columns)
            pending = []
            if not complete and not status and not search:
                pending = process.build_pending_rows(process.pending_rows(self.request), columns)
            return {"rows": rows, "pending_rows": pending, "page_obj": page, "is_paginated": page.has_other_pages()}
        except (DatabaseError, AttributeError, ValueError) as exc:
            logger.exception("Failed to load %s %s table", process.slug, "complete" if complete else "main")
            return {
                "rows": [],
                "pending_rows": [],
                "page_obj": None,
                "is_paginated": False,
                "table_error": str(exc),
            }

    def querystring(self, **overrides):
        """Current query params minus `page`, for filter-preserving links."""
        params = self.request.GET.copy()
        params.pop("page", None)
        for key, value in overrides.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        encoded = params.urlencode()
        return f"&{encoded}" if encoded else ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        process = self.process
        ctx.update(
            {
                "process": process,
                "process_slug": process.slug,
                "process_label": process.label,
                "page_icon": process.icon,
                "submenu": self.submenu,
                "status": self.request.GET.get("status", ""),
                "search": self.request.GET.get("q", "").strip(),
                "status_choices": process.status_choices(),
                "search_placeholder": process.search_placeholder,
                "sort": self.request.GET.get("sort", ""),
                "sort_dir": "desc" if self.request.GET.get("dir") == "desc" else "asc",
                "sort_querystring": self.querystring(sort=None, dir=None, page=None),
                "page_sizes": PAGE_SIZES,
                "per_page": self.page_size(),
                "querystring": self.querystring(),
                "processes": PROCESSES,
                "breadcrumbs": [
                    {"label": process.label, "url": reverse("process:main", kwargs={"process": process.slug})},
                    {"label": "Main Table" if self.submenu == "main" else "Complete Table"},
                ],
            }
        )
        return ctx


class ProcessMainTableView(ProcessTableView):
    """Main Table - the operational screen: material waiting to be
    initiated at this process, followed by its live transactions, each
    with its working action button."""

    template_name = "process/main_table.html"
    submenu = "main"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        process = self.process
        columns = process.main_columns
        ctx.update(
            {
                "page_title": f"{process.label} - Main Table",
                "page_subtitle": process.main_description,
                "columns": columns,
                "has_actions": True,
                "create_url": reverse(process.create_url_name) if process.create_url_name else "",
                "create_label": process.create_label,
            }
        )
        ctx.update(self.load_rows(columns, complete=False))
        return ctx


class ProcessCompleteTableView(ProcessTableView):
    """Complete Table - every record this process has ever produced, with
    the full field set, searchable, filterable and paginated."""

    template_name = "process/complete_table.html"
    submenu = "complete"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        process = self.process
        columns = process.complete_columns
        ctx.update(
            {
                "page_title": f"{process.label} - Complete Table",
                "page_subtitle": process.complete_description,
                "columns": columns,
                "has_actions": False,
                "create_url": "",
            }
        )
        ctx.update(self.load_rows(columns, complete=True))
        return ctx


class LegacyListRedirectView(RedirectView):
    """The per-app list URLs (rolling:list, forming:list, ...) predate the
    dynamic process screens. They now redirect to the canonical Main Table
    so there is exactly one table implementation, while every existing
    link, bookmark and `{% url %}` reference keeps working."""

    permanent = False
    query_string = True
    process_slug = ""

    def get_redirect_url(self, *args, **kwargs):
        return reverse("process:main", kwargs={"process": self.process_slug})
