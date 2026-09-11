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

# Virtual Main Table status: not a value any record stores, just a filter
# that narrows the table to the rows waiting to be initiated here.
INCOMING_STATUS = "incoming"


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

    def incoming_rows(self, columns, *, status, search):
        """Material the previous process completed and this one has not
        picked up yet. Incoming rows are part of the Main Table itself, so
        a search narrows them rather than hiding them; only filtering on a
        real status of this process takes them off the screen."""
        process = self.process
        records = process.incoming_queryset(self.request)
        if records is None:
            return []
        if status and status != INCOMING_STATUS:
            return []
        if search:
            records = process.previous.filter_queryset(records, search=search)
        return process.build_incoming_rows(records, columns)

    def load_rows(self, columns, *, complete):
        """Fetch + render rows, degrading to a visible error state rather
        than a 500 if the query or a column accessor fails."""
        process = self.process
        status = self.request.GET.get("status", "")
        search = self.request.GET.get("q", "").strip()
        try:
            incoming = [] if complete else self.incoming_rows(columns, status=status, search=search)
            if not complete and status == INCOMING_STATUS:
                # The virtual "Incoming" filter shows nothing but incoming.
                source = process.main_queryset(self.request).none()
                status = ""
            else:
                source = process.complete_queryset(self.request) if complete else process.main_queryset(self.request)
            queryset = process.filter_queryset(source, status=status, search=search)
            queryset = process.sort_queryset(
                queryset, columns,
                sort=self.request.GET.get("sort", ""),
                direction=self.request.GET.get("dir", "asc"),
            )
            page = self.paginate(queryset)
            rows = process.build_rows(page.object_list, columns)
            return {
                "rows": rows,
                "incoming_rows": incoming,
                "incoming_count": len(incoming),
                "incoming_from": process.previous.label if process.previous else "",
                "page_obj": page,
                "is_paginated": page.has_other_pages(),
            }
        except (DatabaseError, AttributeError, ValueError) as exc:
            logger.exception("Failed to load %s %s table", process.slug, "complete" if complete else "main")
            return {
                "rows": [],
                "incoming_rows": [],
                "incoming_count": 0,
                "incoming_from": "",
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

    def status_choices(self):
        """The Main Table can also hold rows that are not this process's
        records at all, so it offers "Incoming" alongside its own open
        statuses."""
        choices = list(self.process.status_choices(self.submenu))
        if self.submenu == "main" and self.process.previous is not None:
            choices = [(INCOMING_STATUS, "Incoming")] + choices
        return choices

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
                "status_choices": self.status_choices(),
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
