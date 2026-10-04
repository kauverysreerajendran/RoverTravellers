import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.master_data.models import Location, Plant
from apps.masters.models import (
    CoilMaster, DiameterMaster, DiameterTravellerMapping, RackMaster, SurfaceFinish, TravellerNo, TravellerType,
    WireSerialMaster,
)
from apps.masters import services as masters_services

from . import services
from .models import RollingBatch, RollingBatchCoil


class RollingWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")
        self.traveller_type = TravellerType.objects.create(seq_no=1, name="U1UM UDR")
        self.traveller_no = TravellerNo.objects.create(code="1", label="Pending label")
        self.finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.diameter = DiameterMaster.objects.create(raw_material_id="RM-093", diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.create(
            traveller_type=self.traveller_type, raw_material=self.diameter,
            f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
        )
        # Three serials mirroring the master: SB110 already used, SB111/SB112 free.
        for order, (prefix, seq, status) in enumerate(
            [("SB", 110, "Used"), ("SB", 111, "Available"), ("SB", 112, "Available")], start=1110
        ):
            WireSerialMaster.objects.create(
                serial_no=WireSerialMaster.format_serial(prefix, seq),
                prefix=prefix, sequence=seq, sort_order=order, status=status,
            )
        self.rack = RackMaster.objects.create(rack_code="R1")
        self.coil1 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("22.00"), rack=self.rack)
        self.coil2 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("19.50"), rack=self.rack)

        # Completing a batch auto-stages its output as Forming WIP, which
        # needs a WIP location to exist.
        plant = Plant.objects.create(code="PLANT1", name="Test Plant")
        Location.objects.create(plant=plant, code="WIP-FORMING", name="Forming WIP Area", location_type="wip")

    def test_wire_serial_takes_next_available_from_master(self):
        self.assertEqual(masters_services.generate_wire_serial(), "SB111")
        self.assertEqual(
            WireSerialMaster.objects.get(serial_no="SB111").status, "Used"
        )

    def test_wire_serials_issue_in_order_without_reuse(self):
        self.assertEqual(masters_services.generate_wire_serial(), "SB111")
        self.assertEqual(masters_services.generate_wire_serial(), "SB112")

    def test_wire_serial_exhaustion_raises(self):
        masters_services.generate_wire_serial()
        masters_services.generate_wire_serial()
        with self.assertRaises(ValidationError):
            masters_services.generate_wire_serial()

    def test_serial_format_pads_to_two_digits(self):
        self.assertEqual(WireSerialMaster.format_serial("SA", 1), "SA01")
        self.assertEqual(WireSerialMaster.format_serial("SB", 110), "SB110")
        self.assertEqual(WireSerialMaster.format_serial("SC", 1000), "SC1000")

    def test_initiate_batch_single_coil(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        self.assertEqual(batch.wire_serial, "SB111")
        self.assertEqual(batch.wire_diameter_mm, Decimal("0.93"))
        self.assertEqual(batch.f_thickness_mm, Decimal("0.41"))
        self.assertEqual(batch.f_width_mm, Decimal("1.78"))
        self.coil1.refresh_from_db()
        self.assertEqual(self.coil1.weight_kg, Decimal("4.00"))
        self.assertEqual(self.coil1.status, "In Stock")

    def test_initiate_batch_multiple_coils_must_match_total(self):
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("18.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("10.00")), (self.coil2.coil_id, Decimal("5.00"))],
                user=self.admin,
            )

    def test_coil_marked_consumed_when_fully_used(self):
        services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("22.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("22.00"))], user=self.admin,
        )
        self.coil1.refresh_from_db()
        self.assertEqual(self.coil1.status, "Consumed")
        self.diameter.refresh_from_db()
        self.assertEqual(self.diameter.active_coils, 1)  # only coil2 remains In Stock

    def test_cannot_take_more_than_coil_has(self):
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("50.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("50.00"))], user=self.admin,
            )

    def test_missing_mapping_blocks_batch(self):
        other_type = TravellerType.objects.create(seq_no=2, name="U1UL UDR")
        with self.assertRaises(ValidationError):
            services.initiate_rolling_batch(
                traveller_type=other_type, traveller_no=self.traveller_no, finish=self.finish,
                required_box=30, wire_weight_issued_kg=Decimal("18.00"),
                coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
            )

    def test_complete_batch_calculates_wastage(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        services.complete_rolling_batch(
            batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
            finished_weight_kg=Decimal("17.20"), user=self.admin,
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, "Completed")
        self.assertEqual(batch.wastage_kg, Decimal("0.80"))

    def test_cannot_complete_batch_twice(self):
        batch = services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=self.traveller_no, finish=self.finish,
            required_box=30, wire_weight_issued_kg=Decimal("18.00"),
            coil_weights=[(self.coil1.coil_id, Decimal("18.00"))], user=self.admin,
        )
        services.complete_rolling_batch(
            batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
            finished_weight_kg=Decimal("17.20"), user=self.admin,
        )
        with self.assertRaises(ValidationError):
            services.complete_rolling_batch(
                batch, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
                finished_weight_kg=Decimal("17.20"), user=self.admin,
            )


class StockCheckTests(TestCase):
    """Stock Check before Rolling: services.check_stock, POST
    /api/rolling/stock-check/ and the optional pre-fill on /rolling/create/."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")
        self.traveller_type = TravellerType.objects.create(seq_no=1, name="U1UM UDR")
        self.unmapped_type = TravellerType.objects.create(seq_no=2, name="U1UL UDR")
        self.traveller_no = TravellerNo.objects.create(code="1")
        self.finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.diameter = DiameterMaster.objects.create(raw_material_id="RM-093", diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.create(
            traveller_type=self.traveller_type, raw_material=self.diameter,
            f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
        )
        WireSerialMaster.objects.create(serial_no="SB111", prefix="SB", sequence=111, sort_order=1, status="Available")
        self.rack = RackMaster.objects.create(rack_code="R1")
        self.coil1 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("22.00"), rack=self.rack)
        self.coil2 = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("19.50"))
        consumed = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("5.00"))
        masters_services.consume_coil(consumed, Decimal("5.00"))  # Consumed coils never count
        self.client.force_login(self.admin)
        self.url = reverse("api-rolling-stock-check")

    def _check(self, metres):
        return services.check_stock(self.traveller_type.pk, self.traveller_no.pk, metres)

    def _body(self, metres, traveller_type=None):
        return {
            "traveller_type_id": (traveller_type or self.traveller_type).pk,
            "traveller_no_id": self.traveller_no.pk,
            "required_m": metres,
        }

    def _post(self, body):
        return self.client.post(self.url, body, content_type="application/json")

    def _create_url(self, metres="1000"):
        return (f"{reverse('rolling:create')}?traveller_type={self.traveller_type.pk}"
                f"&traveller_no={self.traveller_no.pk}&required_m={metres}")

    # -- conversion -------------------------------------------------------
    def test_required_kg_from_metres(self):
        # pi/4 * 1^2 * 1000 * 7.85 / 1000 = 6.165 kg
        self.assertEqual(services.required_kg_from_metres(Decimal("1"), Decimal("1000")), Decimal("6.17"))
        self.assertEqual(services.required_kg_from_metres(Decimal("0.93"), Decimal("1000")), Decimal("5.33"))

    # -- service ----------------------------------------------------------
    def test_stock_available(self):
        result = self._check("1000")
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["available"])
        self.assertEqual(result["raw_material"], {"raw_material_id": "RM-093", "diameter_mm": Decimal("0.93")})
        self.assertEqual((result["f_thickness_mm"], result["f_width_mm"]), (Decimal("0.41"), Decimal("1.78")))
        self.assertEqual(result["required_m"], Decimal("1000"))
        self.assertEqual(result["required_kg"], Decimal("5.33"))
        self.assertEqual(result["total_available_kg"], Decimal("41.50"))
        self.assertEqual(result["shortfall_kg"], Decimal("0.00"))
        self.assertEqual([c.pk for c in result["coils"]], [self.coil1.pk, self.coil2.pk])

    def test_insufficient_stock_reports_shortfall(self):
        result = self._check("10000")
        self.assertEqual(result["status"], "insufficient")
        self.assertFalse(result["available"])
        self.assertEqual(result["required_kg"], Decimal("53.32"))
        self.assertEqual(result["shortfall_kg"], Decimal("11.82"))  # 53.32 - 41.50

    def test_no_mapping_is_a_normal_result(self):
        result = services.check_stock(self.unmapped_type.pk, self.traveller_no.pk, "1000")
        self.assertEqual(result["status"], "no_mapping")
        self.assertFalse(result["available"])
        self.assertEqual(result["message"], services.NO_MAPPING_MESSAGE)
        self.assertIsNone(result["raw_material"])
        self.assertEqual(result["coils"], [])

    def test_invalid_or_missing_inputs(self):
        tt, tn = self.traveller_type.pk, self.traveller_no.pk
        cases = [
            ((None, tn, "10"), "traveller_type_id"),
            ((999999, tn, "10"), "traveller_type_id"),
            (("abc", tn, "10"), "traveller_type_id"),
            ((tt, None, "10"), "traveller_no_id"),
            ((tt, tn, None), "required_m"),
            ((tt, tn, "0"), "required_m"),
            ((tt, tn, "-5"), "required_m"),
            ((tt, tn, "ten"), "required_m"),
            ((tt, tn, "NaN"), "required_m"),
        ]
        for args, field in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValidationError) as ctx:
                    services.check_stock(*args)
                self.assertIn(field, ctx.exception.message_dict)

    def _snapshot(self):
        from apps.audit.models import AuditLog
        from apps.production.models import ProductionLot

        self.diameter.refresh_from_db()
        return {
            "batches": RollingBatch.objects.count(),
            "batch_coils": RollingBatchCoil.objects.count(),
            "lots": ProductionLot.objects.count(),
            "audit": AuditLog.objects.count(),
            "serials": list(WireSerialMaster.objects.values_list("serial_no", "status")),
            "coils": list(CoilMaster.objects.order_by("pk").values_list("pk", "weight_kg", "status")),
            "diameter": (self.diameter.total_stock, self.diameter.active_coils),
        }

    def test_check_is_read_only(self):
        before = self._snapshot()
        self._check("1000")
        self._check("100000")
        services.check_stock(self.unmapped_type.pk, self.traveller_no.pk, "1000")
        self._post(self._body("1000"))
        self._post(self._body("100000"))
        self.client.get(self._create_url())
        self.assertEqual(self._snapshot(), before)

    # -- endpoint ---------------------------------------------------------
    def test_endpoint_available(self):
        res = self._post(self._body("1000"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["raw_material"], {"raw_material_id": "RM-093", "diameter_mm": "0.93"})
        self.assertEqual(data["required_kg"], "5.33")
        self.assertEqual(data["total_available_kg"], "41.50")
        self.assertEqual([c["coil_id"] for c in data["coils"]], [self.coil1.pk, self.coil2.pk])
        self.assertEqual(data["coils"][0]["rack_code"], "R1")
        self.assertIsNone(data["inventory_url"])
        self.assertEqual(data["proceed_url"], self._create_url())

    def test_endpoint_insufficient_links_to_inventory(self):
        data = self._post(self._body("10000")).json()
        self.assertEqual(data["status"], "insufficient")
        self.assertEqual(data["shortfall_kg"], "11.82")
        self.assertIsNone(data["proceed_url"])
        self.assertEqual(data["inventory_url"], reverse("masters:diameter_detail", kwargs={"pk": "RM-093"}))

    def test_endpoint_no_mapping(self):
        res = self._post(self._body("1000", self.unmapped_type))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "no_mapping")
        self.assertEqual(data["message"], services.NO_MAPPING_MESSAGE)
        self.assertIsNone(data["proceed_url"])
        self.assertIsNone(data["inventory_url"])

    def test_endpoint_invalid_inputs_return_field_errors(self):
        res = self._post({"required_m": "0"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["errors"]), {"traveller_type_id", "traveller_no_id", "required_m"})

    def test_endpoint_hides_proceed_from_non_operators(self):
        viewer = User.objects.create_user(username="viewer", password="x")
        self.client.force_login(viewer)
        data = self._post(self._body("1000")).json()
        self.assertTrue(data["available"])
        self.assertIsNone(data["proceed_url"])

    def test_endpoint_requires_login_and_csrf(self):
        from django.test import Client

        self.client.logout()
        self.assertIn(self._post(self._body("1000")).status_code, (401, 403))

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        res = strict.post(self.url, self._body("1000"), content_type="application/json")
        self.assertEqual(res.status_code, 403)

    # -- screens ----------------------------------------------------------
    def test_header_stock_check_on_every_screen(self):
        for url in (
            reverse("dashboard:overview"),
            reverse("process:main", kwargs={"process": "rolling"}),
            reverse("process:main", kwargs={"process": "forming"}),
        ):
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertContains(res, 'data-bs-target="#stockCheckModal"', count=1)
                self.assertContains(res, 'id="stockCheckModal"', count=1)
                self.assertContains(
                    res, f'<option value="{self.traveller_type.pk}">1 – U1UM UDR</option>', html=True
                )

    def test_rolling_main_table_keeps_new_batch_button(self):
        res = self.client.get(reverse("process:main", kwargs={"process": "rolling"}))
        self.assertContains(res, "New Rolling Batch")

    def test_signed_out_pages_have_no_stock_check(self):
        self.client.logout()
        res = self.client.get(reverse("accounts:login"))
        self.assertNotContains(res, "stockCheckModal")

    def test_create_page_without_params_is_unchanged(self):
        res = self.client.get(reverse("rolling:create"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["form"].initial, {})
        self.assertIsNone(res.context["stock_check"])
        self.assertNotContains(res, "stockCheckHint")

    def test_create_page_prefills_from_stock_check(self):
        res = self.client.get(self._create_url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.context["form"].initial,
            {"traveller_type_id": self.traveller_type.pk, "traveller_no": self.traveller_no.pk},
        )
        self.assertContains(res, f'name="traveller_type_id" value="{self.traveller_type.pk}"')
        self.assertContains(res, f'<option value="{self.traveller_no.pk}" selected>1</option>', html=True)
        self.assertContains(res, "stockCheckHint")
        self.assertContains(res, "5.33 kg")

    def test_create_page_ignores_bad_params(self):
        res = self.client.get(f"{reverse('rolling:create')}?traveller_type=999999&traveller_no=x&required_m=-1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["form"].initial, {})
        self.assertNotContains(res, "stockCheckHint")

    def test_create_still_submits_after_prefill(self):
        self.client.get(self._create_url())
        res = self.client.post(reverse("rolling:create"), {
            "traveller_type_id": self.traveller_type.pk, "traveller_no": self.traveller_no.pk,
            "finish": self.finish.pk, "required_box": 30, "wire_weight_issued_kg": "5.33",
            "coils_json": json.dumps([{"coil_id": self.coil1.pk, "weight_taken_kg": "5.33"}]),
        })
        self.assertRedirects(res, reverse("rolling:list"), fetch_redirect_response=False)
        self.assertEqual(RollingBatch.objects.get().wire_weight_issued_kg, Decimal("5.33"))
        self.coil1.refresh_from_db()
        self.assertEqual(self.coil1.weight_kg, Decimal("16.67"))


class TravellerOverviewTests(TestCase):
    """GET /api/rolling/stock-check/traveller/: Required M guidance and the
    current stage of a traveller's material, linked to that stage's screen."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", email="root@example.com", password="x")
        self.traveller_type = TravellerType.objects.create(seq_no=1, name="U1UM UDR")
        self.unmapped_type = TravellerType.objects.create(seq_no=2, name="U1UL UDR")
        self.no1 = TravellerNo.objects.create(code="1")
        self.no2 = TravellerNo.objects.create(code="2")
        self.finish = SurfaceFinish.objects.create(finish_name="Indigo")
        self.diameter = DiameterMaster.objects.create(raw_material_id="RM-093", diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.create(
            traveller_type=self.traveller_type, raw_material=self.diameter,
            f_thickness_mm=Decimal("0.41"), f_width_mm=Decimal("1.78"),
        )
        for order, seq in enumerate((111, 112), start=1):
            WireSerialMaster.objects.create(serial_no=f"SB{seq}", prefix="SB", sequence=seq, sort_order=order)
        self.coil = masters_services.receive_coil(raw_material=self.diameter, weight_kg=Decimal("100.00"))
        plant = Plant.objects.create(code="PLANT1", name="Test Plant")
        Location.objects.create(plant=plant, code="WIP-FORMING", name="Forming WIP Area", location_type="wip")

        # SB111: rolled and completed -> waiting on Forming. SB112: still rolling.
        self.done = self._initiate(self.no1, "10.00")
        services.complete_rolling_batch(
            self.done, rolled_thickness_mm=Decimal("0.41"), rolled_width_mm=Decimal("1.78"),
            finished_weight_kg=Decimal("9.50"), user=self.admin,
        )
        self.rolling = self._initiate(self.no2, "30.00")
        self.client.force_login(self.admin)
        self.url = reverse("api-rolling-stock-check-traveller")

    def _initiate(self, traveller_no, kg):
        return services.initiate_rolling_batch(
            traveller_type=self.traveller_type, traveller_no=traveller_no, finish=self.finish,
            required_box=10, wire_weight_issued_kg=Decimal(kg),
            coil_weights=[(self.coil.coil_id, Decimal(kg))], user=self.admin,
        )

    def test_metres_from_kg_is_inverse_and_rounds_down(self):
        self.assertEqual(services.metres_from_kg(Decimal("1"), Decimal("6.165")), Decimal("999"))
        self.assertEqual(services.metres_from_kg(Decimal("0.93"), Decimal("5.33")), Decimal("999"))

    def test_guidance_for_required_m(self):
        result = services.traveller_overview(self.traveller_type.pk)
        self.assertEqual(result["stock"]["total_kg"], Decimal("60.00"))  # 100 - 10 - 30
        self.assertEqual(result["stock"]["total_m"], services.metres_from_kg(Decimal("0.93"), Decimal("60.00")))
        self.assertEqual(result["history"]["batch_count"], 2)
        self.assertEqual(result["history"]["last_kg"], Decimal("30.00"))
        self.assertEqual(result["history"]["average_kg"], Decimal("20.00"))
        self.assertEqual(result["history"]["average_m"], services.metres_from_kg(Decimal("0.93"), Decimal("20.00")))

    def test_stages_follow_the_registry(self):
        from apps.production.process_registry import PROCESSES

        result = services.traveller_overview(self.traveller_type.pk)
        self.assertEqual([s["process"].slug for s in result["stages"]], [p.slug for p in PROCESSES])
        counts = {s["process"].slug: s["count"] for s in result["stages"]}
        self.assertEqual(counts["rolling"], 1)
        self.assertEqual(counts["forming"], 1)
        self.assertEqual(sum(counts.values()), 2)
        states = {row["wire_serial"]: (row["process"].slug, row["state"]) for row in result["lots"]}
        self.assertEqual(states, {"SB111": ("forming", "waiting"), "SB112": ("rolling", "in_progress")})

    def test_traveller_no_narrows_the_lots(self):
        result = services.traveller_overview(self.traveller_type.pk, self.no2.pk)
        self.assertEqual([row["wire_serial"] for row in result["lots"]], ["SB112"])

    def test_unmapped_type_has_no_guidance_but_still_answers(self):
        result = services.traveller_overview(self.unmapped_type.pk)
        self.assertIsNone(result["raw_material"])
        self.assertIsNone(result["stock"])
        self.assertEqual(result["lot_count"], 0)

    def test_invalid_inputs(self):
        for args, field in (((None,), "traveller_type_id"), ((999999,), "traveller_type_id"),
                            ((self.traveller_type.pk, 999999), "traveller_no_id")):
            with self.subTest(args=args):
                with self.assertRaises(ValidationError) as ctx:
                    services.traveller_overview(*args)
                self.assertIn(field, ctx.exception.message_dict)
        self.assertEqual(self.client.get(self.url).status_code, 400)

    def test_endpoint_links_each_lot_to_its_stage_screen(self):
        data = self.client.get(self.url, {"traveller_type_id": self.traveller_type.pk}).json()
        self.assertEqual(data["stock"]["total_kg"], "60.00")
        links = {row["wire_serial"]: row["url"] for row in data["lots"]}
        self.assertEqual(links["SB111"], reverse("process:main", kwargs={"process": "forming"}) + "?q=SB111")
        self.assertEqual(links["SB112"], reverse("process:main", kwargs={"process": "rolling"}) + "?q=SB112")
        # Following a link lands on a screen that shows that lot and not the other.
        for serial, other in (("SB111", "SB112"), ("SB112", "SB111")):
            with self.subTest(serial=serial):
                page = self.client.get(links[serial])
                self.assertContains(page, serial)
                self.assertNotContains(page, other)
        stage_urls = {s["slug"]: s["url"] for s in data["stages"]}
        self.assertEqual(stage_urls["forming"], reverse("process:main", kwargs={"process": "forming"}))

    def test_overview_is_read_only(self):
        from apps.production.models import ProductionLot

        before = (RollingBatch.objects.count(), ProductionLot.objects.count(),
                  list(CoilMaster.objects.values_list("pk", "weight_kg", "status")),
                  list(WireSerialMaster.objects.values_list("serial_no", "status")))
        self.client.get(self.url, {"traveller_type_id": self.traveller_type.pk, "traveller_no_id": self.no1.pk})
        after = (RollingBatch.objects.count(), ProductionLot.objects.count(),
                 list(CoilMaster.objects.values_list("pk", "weight_kg", "status")),
                 list(WireSerialMaster.objects.values_list("serial_no", "status")))
        self.assertEqual(after, before)
