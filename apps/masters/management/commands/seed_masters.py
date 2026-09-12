import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.masters.models import (
    CoilMaster,
    DiameterMaster,
    DiameterTravellerMapping,
    Machine,
    RackMaster,
    RackZone,
    StorageRack,
    SurfaceFinish,
    TravellerNo,
    TravellerType,
    WireSerialMaster,
)

# Wire serial master blocks, issued strictly in this order.
WIRE_SERIAL_PREFIXES = ["SA", "SB", "SC"]
WIRE_SERIALS_PER_PREFIX = 1000

# The serial currently in use on the shop floor; everything up to and
# including it is historical and marked Used when seeding.
CURRENT_WIRE_SERIAL = ("SB", 110)

SURFACE_FINISHES = ["Indigo", "Endura", "Plain/Polish", "Nickel +", "NMAX"]

# Provisional coil-storage bay and machine master. Both are real master
# tables the shop floor will own; until the business supplies them, a
# small set is seeded here so that the process screens and the history
# generator have master rows to read rather than invent.
RACK_COUNT = 6
MACHINE_SUFFIXES = ["A", "B"]
# Machine.STAGE_CHOICES carries a catch-all that is not a process.
GENERIC_MACHINE_STAGE = "general"

# Storage rack zones: the physical grids material sits on between the
# processes. `process_slug` names the process whose completion (Rolling) or
# receipt (Finished Goods) puts material on the zone; RackZone validates it
# against the process registry on save, so a slug that is not a process
# fails here rather than seeding a dead zone.
RACK_ZONES = [
    {
        "code": "FORMING", "name": "Forming Rack", "process_slug": "rolling",
        "rack_prefix": "FR", "rack_count": 10, "rows": 5, "columns": 5,
    },
    {
        "code": "FG", "name": "Finished Goods Rack", "process_slug": "finished_goods",
        "rack_prefix": "FG", "rack_count": 5, "rows": 5, "columns": 5,
    },
]

# Official Traveller Type Master. Row 17 and 63 both read "RE2 UDR" in the
# source document - kept as-is; seq_no is the real business key.
#
# Client corrections applied on top of the original 1-68 list:
#    1  "U1M UDR"                        -> "U1UM UDR"
#   27  "E2F / H2 HO"                    -> "E2F", with "H2 HO" split out as a new type (69)
#   33  "RC1 HD TN (SAB UDR) R&F NT"     -> "RC1 HD TW (CISDUDR)"
#   40  "RU1 SM UDR (Kanai Wt NT)"       -> "RU1 SM UDR"
#   41  "RC2 HR MT / RS4 FLAT / RS4 Rod" -> "RC2 HR MT", split into new types "RSY FLAT" (70) and "RSY Rd" (71)
#   52  "CON 7/16 R&F"                   -> "CON 7/16"
#   53  "RU1 SMK UDR (Kanai Wt) Blue (NFC)" -> "RU1 SMK UDR Blue (NFC)"
TRAVELLER_TYPES = [
    (1, "U1UM UDR"), (2, "U1UL UDR"), (3, "EM1 UDR"), (4, "EM1 FLAT"), (5, "EM1 HO"),
    (6, "EM2 UDR"), (7, "EM2 FLAT"), (8, "EM2 HO"), (9, "M1 FLAT"), (10, "M1 UDR"),
    (11, "M1 HO"), (12, "RC1 U1M UDR"), (13, "RC1 HNO"), (14, "RMS HO"), (15, "U1 CEL UDR"),
    (16, "U1 MM UDR"), (17, "RE2 UDR"), (18, "M2 UDR"), (19, "M2 HO"),
    (20, 'U½ FL UDR (RCL UDR)'), (21, "U2 U1M UDR"), (22, "P1 HNO"), (23, "EP1 HNO"),
    (24, "EP2 HNO"), (25, "EH2 HO"), (26, "EH2 UDR"), (27, "E2F"), (28, "EL1 UDR"),
    (29, "OS"), (30, "EL2 UDR"), (31, "RSR UDR"), (32, "RC1 HR MT"),
    (33, "RC1 HD TW (CISDUDR)"), (34, "RU1 HM UDR"),
    (35, "RU1 M1 UDR (Rover M1 UDR) RCMM UDR"), (36, "RC1 UDR EMT"), (37, "RC1 UDR MT"),
    (38, "REL1 UDR EM"), (39, "REL HD EM"), (40, "RU1 SM UDR"),
    (41, "RC2 HR MT"), (42, "CON 7/16 FLAT, RD"), (43, "SD 21/32"),
    (44, "CON 11/16 +"), (45, 'SD UDR 1"'), (46, "J TYPE (9.1 mm) R&F"), (47, "C1 FLAT"),
    (48, "C2 FLAT"), (49, "C3 FLAT"), (50, "FW2F"), (51, "G Rod"), (52, "CON 7/16"),
    (53, "RU1 SMK UDR Blue (NFC)"), (54, 'RESL "R"'), (55, "RC1 UM HO"),
    (56, "ES FLAT"), (57, "RESL UDR"), (58, 'RDF "J" 11.10 mm'), (59, "RU1 EL UDR"),
    (60, "RC2 UM UDR"), (61, "RC1 EMT UDR"), (62, "RC1 MM UDR"), (63, "RE2 UDR"),
    (64, "OS HO"), (65, "RE MS UDR"), (66, "REL1 HD EM"), (67, "RU1 SMR UDR"), (68, "EL1 FLAT"),
    # New types split out of rows 27 and 41 by client correction.
    (69, "H2 HO"), (70, "RSY FLAT"), (71, "RSY Rd"),
]

# Official Raw Material Diameter Master (65 rows, 0.38mm to 3.60mm).
DIAMETERS_MM = [
    "0.38", "0.41", "0.43", "0.46", "0.48", "0.50", "0.52", "0.53", "0.55", "0.56",
    "0.58", "0.60", "0.62", "0.63", "0.65", "0.68", "0.70", "0.72", "0.73", "0.75",
    "0.76", "0.80", "0.82", "0.85", "0.86", "0.87", "0.90", "0.93", "0.95", "1.00",
    "1.04", "1.07", "1.10", "1.14", "1.17", "1.20", "1.25", "1.30", "1.40", "1.43",
    "1.45", "1.50", "1.60", "1.65", "1.70", "1.80", "1.85", "1.90", "2.00", "2.10",
    "2.15", "2.20", "2.30", "2.45", "2.50", "2.56", "2.65", "2.85", "3.00", "3.10",
    "3.20", "3.30", "3.40", "3.50", "3.60",
]

# Provisional fine-gauge additions requested by the client: every 0.01mm step
# from 0.10 to 0.98. Steps already present in the official list above are
# skipped, so this only fills the gaps.
PROVISIONAL_DIAMETERS_MM = [f"{value / 100:.2f}" for value in range(10, 99)]


class Command(BaseCommand):
    help = "Seed the official Traveller Type Master (68 rows) and Raw Material Diameter Master (65 rows), plus supporting master data."

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_traveller_types()
        self._seed_diameters()
        self._seed_surface_finish()
        self._seed_traveller_numbers()
        self._seed_racks()
        self._seed_rack_zones()
        self._seed_machines()
        self._seed_confirmed_mapping()
        self._seed_wire_serials()
        self._seed_sample_rack_and_coils()
        self.stdout.write(self.style.SUCCESS("Masters seeded successfully."))

    def _seed_traveller_types(self):
        for seq_no, name in TRAVELLER_TYPES:
            TravellerType.objects.update_or_create(seq_no=seq_no, defaults={"name": name})
        self.stdout.write(f"  Traveller types: {TravellerType.objects.count()} rows")

    def _seed_diameters(self):
        # dict.fromkeys keeps order while dropping the overlap between the
        # official list and the 0.10-0.98 provisional range.
        for value in dict.fromkeys(DIAMETERS_MM + PROVISIONAL_DIAMETERS_MM):
            diameter = Decimal(value)
            raw_material_id = DiameterMaster.generate_raw_material_id(diameter)
            DiameterMaster.objects.update_or_create(
                raw_material_id=raw_material_id, defaults={"diameter_mm": diameter}
            )
        total = DiameterMaster.objects.count()
        fine = DiameterMaster.objects.filter(diameter_mm__gte=Decimal("0.10"), diameter_mm__lte=Decimal("0.98")).count()
        self.stdout.write(
            f"  Diameters: {total} rows ({len(DIAMETERS_MM)} official + provisional 0.10-0.98 fill; "
            f"{fine} rows now in the 0.10-0.98 range)"
        )

    def _seed_surface_finish(self):
        for name in SURFACE_FINISHES:
            SurfaceFinish.objects.get_or_create(finish_name=name)
        self.stdout.write(f"  Surface finishes: {SurfaceFinish.objects.count()} rows ({', '.join(SURFACE_FINISHES)})")

    def _seed_traveller_numbers(self):
        TravellerNo.objects.get_or_create(code="1")
        TravellerNo.objects.get_or_create(code="0")

        # Traveller No master (spec section 3.2): "1/0" through "25/0", plus
        # plain Traveller Nos "1" through "35" for production requirements
        # that use a bare number rather than the n/0 form.
        for n in range(1, 26):
            code = f"{n}/0"
            TravellerNo.objects.get_or_create(code=code, defaults={"label": code})
        for n in range(1, 36):
            code = str(n)
            TravellerNo.objects.get_or_create(code=code, defaults={"label": code})
        self.stdout.write(f"  Traveller numbers: {TravellerNo.objects.count()} rows")

    def _seed_racks(self):
        """Coil storage racks. The Raw Material Master Design (Phase 1)
        document names only R1; the rest are a small provisional bay so
        that anything distributing coils across racks has more than one
        to choose from. Replace with the real rack master when it exists."""
        for number in range(1, RACK_COUNT + 1):
            RackMaster.objects.get_or_create(rack_code=f"R{number}", defaults={"capacity": 10})
        self.stdout.write(
            f"  Racks: {RackMaster.objects.count()} rows (R1 from the Phase 1 document, "
            f"R2-R{RACK_COUNT} provisional)"
        )

    def _seed_rack_zones(self):
        """Idempotent: zones and racks are matched on their codes and slots
        are only ever added, never recreated, so re-running this never moves
        material that is already on a rack."""
        for spec in RACK_ZONES:
            zone, _ = RackZone.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "process_slug": spec["process_slug"],
                    "rack_count": spec["rack_count"],
                    "rows": spec["rows"],
                    "columns": spec["columns"],
                    "is_active": True,
                },
            )
            added = 0
            for position in range(1, spec["rack_count"] + 1):
                rack, created = StorageRack.objects.update_or_create(
                    zone=zone, code=f"{spec['rack_prefix']}-{position:02d}",
                    defaults={"position": position, "is_active": True},
                )
                # A rack created here built its own slots; an existing one
                # only gains the slots it is missing.
                added += rack.build_slots() if not created else rack.slots.count()
            self.stdout.write(
                f"  {zone.name}: {zone.racks.count()} racks x {zone.rows}x{zone.columns} "
                f"= {zone.slots.count()} slots ({added} created this run)"
            )

    def _seed_machines(self):
        """Machines are master data that the process screens read (Forming
        and Finishing record one on their Initiate screen), so they belong
        here rather than being invented by the history generator - which
        refuses to create master data and stops instead.

        The stage list comes from Machine.STAGE_CHOICES, so a stage added
        to the model is seeded without editing this command. These are
        PROVISIONAL: replace them with the real machine master.
        """
        from apps.master_data.models import Plant

        plant = Plant.active.first() or Plant.objects.get_or_create(
            code="PLANT", defaults={"name": "Plant"}
        )[0]
        created = []
        for stage, label in Machine.STAGE_CHOICES:
            if stage == GENERIC_MACHINE_STAGE:
                continue
            for suffix in MACHINE_SUFFIXES:
                code = f"{stage.upper()}-{suffix}"
                _, was_created = Machine.objects.get_or_create(
                    code=code,
                    defaults={"name": f"{label} {suffix}", "stage": stage, "plant": plant},
                )
                if was_created:
                    created.append(code)
        self.stdout.write(
            f"  Machines: {Machine.objects.count()} rows ({len(created)} created now) - "
            "PROVISIONAL, replace with the real machine master"
        )

    def _seed_confirmed_mapping(self):
        traveller_type = TravellerType.objects.get(seq_no=1)  # U1UM UDR, confirmed == "U1"
        raw_material = DiameterMaster.objects.get(diameter_mm=Decimal("0.93"))
        DiameterTravellerMapping.objects.update_or_create(
            traveller_type=traveller_type,
            defaults={"raw_material": raw_material, "f_thickness_mm": Decimal("0.41"), "f_width_mm": Decimal("1.78")},
        )
        self.stdout.write("  Confirmed mapping: U1UM UDR -> RM-093 (0.93mm), F-Thickness 0.41mm, F-Width 1.78mm")

    def _seed_wire_serials(self):
        """Loads SA01-SA1000, SB01-SB1000, SC01-SC1000 (3000 rows). Everything
        up to and including the current shop-floor serial is marked Used, so
        the next batch picks up exactly where production left off."""
        current_prefix, current_sequence = CURRENT_WIRE_SERIAL
        current_sort_order = (
            WIRE_SERIAL_PREFIXES.index(current_prefix) * WIRE_SERIALS_PER_PREFIX + current_sequence
        )

        existing = set(WireSerialMaster.objects.values_list("serial_no", flat=True))
        new_rows = []
        for block, prefix in enumerate(WIRE_SERIAL_PREFIXES):
            for sequence in range(1, WIRE_SERIALS_PER_PREFIX + 1):
                serial_no = WireSerialMaster.format_serial(prefix, sequence)
                if serial_no in existing:
                    continue
                sort_order = block * WIRE_SERIALS_PER_PREFIX + sequence
                new_rows.append(
                    WireSerialMaster(
                        serial_no=serial_no,
                        prefix=prefix,
                        sequence=sequence,
                        sort_order=sort_order,
                        status="Used" if sort_order <= current_sort_order else "Available",
                        used_at=timezone.now() if sort_order <= current_sort_order else None,
                    )
                )
        if new_rows:
            WireSerialMaster.objects.bulk_create(new_rows, batch_size=500)

        total = WireSerialMaster.objects.count()
        used = WireSerialMaster.objects.filter(status="Used").count()
        next_serial = WireSerialMaster.objects.filter(status="Available").order_by("sort_order").first()
        self.stdout.write(
            f"  Wire serials: {total} rows ({', '.join(WIRE_SERIAL_PREFIXES)}) | "
            f"{used} marked Used through {WireSerialMaster.format_serial(current_prefix, current_sequence)} | "
            f"next serial: {next_serial.serial_no if next_serial else 'none left'}"
        )

    def _seed_sample_rack_and_coils(self):
        """Coil weights come from the Coil Master table in the Raw Material
        Master Design (Phase 1) document: 52.30 / 48.70 / 61.10 / 83.70 kg,
        totalling 245.80 kg. The document illustrates them against 0.40mm,
        which is not one of the 65 official diameters, so they are attached
        to RM-093 (0.93mm) - the diameter the confirmed traveller-type
        mapping uses - to keep the Rolling flow testable."""
        rack, _ = RackMaster.objects.get_or_create(rack_code="R1")
        raw_material = DiameterMaster.objects.get(diameter_mm=Decimal("0.93"))
        for number, weight in [(1, "52.30"), (2, "48.70"), (3, "61.10"), (4, "83.70")]:
            CoilMaster.objects.update_or_create(
                raw_material=raw_material,
                coil_display_number=number,
                defaults={
                    "weight_kg": Decimal(weight),
                    "status": "In Stock",
                    "rack": rack,
                    "supplier": "Bharat Steel Suppliers",
                    "received_date": datetime.date.today(),
                },
            )
        raw_material.recalculate_stock()
        self.stdout.write(
            f"  Coils 1-4 seeded under RM-093 on rack R1 (total stock {raw_material.total_stock} KG)"
        )
