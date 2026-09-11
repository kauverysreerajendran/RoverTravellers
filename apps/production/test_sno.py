"""S.No is the first column of every data table in the front end.

It is presentation only: a continuous row number that runs across pages
and across the incoming rows at the top of a Main Table. It is never a
model field, never sortable and never part of a search or filter.
"""

import re
from decimal import Decimal

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.production import services as prod_services
from apps.production.process_registry import PROCESSES
from apps.production.tests import WorkflowTestBase

TABLE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL)
FIRST_HEADER = re.compile(r"<th[^>]*>(.*?)</th>", re.DOTALL)
# The row number cells, in the order they were rendered.
SNO_CELLS = re.compile(r'<td class="col-sno">\s*(\d+)\s*</td>')


def first_header_of_each_table(body):
    for table in TABLE.findall(body):
        match = FIRST_HEADER.search(table)
        if match is None:
            continue
        # A table whose first cell is a tick-box is a selection widget, not
        # a listing - there is nothing to number.
        if "checkbox" in match.group(1):
            continue
        yield re.sub(r"<[^>]+>", "", match.group(1)).strip()


class ProcessTableSerialNumberTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_every_process_table_leads_with_sno(self):
        for process in PROCESSES:
            for submenu in ("main", "complete"):
                url = reverse(f"process:{submenu}", kwargs={"process": process.slug})
                with self.subTest(url=url):
                    headers = list(first_header_of_each_table(self.client.get(url).content.decode()))
                    self.assertTrue(headers, "no table rendered")
                    self.assertEqual(headers[0], "S.No")

    def test_numbering_continues_onto_the_second_page(self):
        """Page 2 of a 25-row page continues at 26 rather than restarting."""
        self.seed_forming_wip("30000")
        for _ in range(30):
            transaction = self.make_forming(input_qty="100", output_qty="90", rejection_qty="5")
            transaction.status = "completed"
            transaction.save(update_fields=["status"])

        url = reverse("process:complete", kwargs={"process": "forming"})
        first_page = self.client.get(url, {"per_page": 25}).content.decode()
        second_page = self.client.get(url, {"per_page": 25, "page": 2}).content.decode()

        self.assertEqual(SNO_CELLS.findall(first_page)[0], "1")
        self.assertEqual(SNO_CELLS.findall(first_page)[-1], "25")
        self.assertEqual(SNO_CELLS.findall(second_page)[0], "26")

    def test_incoming_rows_are_numbered_before_the_rows_below_them(self):
        """Three incoming rows and two in-progress rows number 1-5, in the
        order they appear - the numbering does not restart mid-table."""
        heat_treatment = next(p for p in PROCESSES if p.slug == "heat_treatment")
        forming = heat_treatment.previous

        for index in range(5):
            lot = self.make_lot(f"WS{index:03d}", Decimal("100"))
            transaction = forming.model.objects.create(
                lot=lot, machine=self.machine_forming, input_quantity=Decimal("100"),
                output_quantity=Decimal("90"), status="in_progress",
                created_by=self.admin, updated_by=self.admin,
            )
            prod_services.complete_stage(transaction, self.admin)
            if index < 2:
                # Two of them are taken up at Heat Treatment, so they show
                # as in-progress rows instead of incoming ones.
                prod_services.initiate_stage(heat_treatment, lot, self.admin, batch_number=f"B{index}")

        response = self.client.get(reverse("process:main", kwargs={"process": "heat_treatment"}))
        numbers = SNO_CELLS.findall(response.content.decode())
        self.assertEqual(numbers, ["1", "2", "3", "4", "5"])
        self.assertEqual(response.context["incoming_count"], 3)

    def test_sno_is_never_sortable_or_searchable(self):
        for process in PROCESSES:
            for name in ("main_columns", "complete_columns"):
                for column in getattr(process, name):
                    self.assertNotEqual(column.label, "S.No")
            self.assertNotIn("sno", " ".join(process.search_fields))


class EverySreenLeadsWithSerialNumberTests(WorkflowTestBase):
    """Walk the URLconf and check every table the app can render without
    arguments. This catches a table added to a new screen without one."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.seed_forming_wip("480")
        transaction = self.make_forming(input_qty="480", output_qty="460", rejection_qty="15")
        prod_services.complete_stage(transaction, self.admin)

    def argument_free_urls(self):
        urls = []

        def walk(patterns, prefix=""):
            for entry in patterns:
                if isinstance(entry, URLResolver):
                    walk(entry.url_patterns, prefix + str(entry.pattern))
                elif isinstance(entry, URLPattern):
                    route = prefix + str(entry.pattern)
                    if "<" in route or "(" in route or route.startswith("admin/"):
                        continue
                    if "logout" in route:
                        # Walking it would sign the test client out and turn
                        # every screen after it into a redirect.
                        continue
                    urls.append("/" + route)

        walk(get_resolver().url_patterns)
        return urls

    def test_every_reachable_table_leads_with_sno(self):
        offenders = []
        checked = 0
        for url in self.argument_free_urls():
            try:
                response = self.client.get(url)
            except Exception:  # a screen needing query parameters, not a table problem
                continue
            if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                continue
            for header in first_header_of_each_table(response.content.decode()):
                checked += 1
                if header != "S.No":
                    offenders.append(f"{url}: first column is {header!r}")
        self.assertGreater(checked, 10, "the walk found almost no tables - it is not testing anything")
        self.assertEqual(offenders, [])
