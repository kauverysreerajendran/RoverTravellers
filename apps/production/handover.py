"""The handover contract every process record implements.

A process hands material to the next process in the registry. For the
generic incoming-rows machinery in `process_registry` to work without
knowing which process it is looking at, every record class - Rolling
batches, the three OperationBase stages and Finished Goods stock - must
expose the same small set of names:

    wire_serial     -> str          the traceable identity of the material
    traveller_type  -> TravellerType
    traveller_no    -> TravellerNo
    surface_finish  -> SurfaceFinish | None
    received_weight -> Decimal | None   what the previous process handed over
    output_weight   -> Decimal | None   what this record hands over
    handover_lot    -> ProductionLot    the carrier the next process initiates against
    completed_at    -> datetime | None

These are properties over fields that already exist; nothing here
duplicates stored data.
"""


class HandoverRecord:
    """Default implementation for records that carry a `lot` FK and an
    `output_quantity`. Subclasses override only what differs."""

    # ORM path from this record to its handover lot, used by the registry
    # to exclude material that the next process has already picked up.
    handover_lot_path = "lot"

    @property
    def handover_lot(self):
        return self.lot

    @property
    def wire_serial(self):
        lot = self.handover_lot
        return lot.wire_serial if lot else ""

    @property
    def traveller_type(self):
        lot = self.handover_lot
        return lot.traveller_type if lot else None

    @property
    def traveller_no(self):
        lot = self.handover_lot
        return lot.traveller_no if lot else None

    @property
    def surface_finish(self):
        """Heat Treatment and Finishing declare their own `surface_finish`
        field, which shadows this property on those concrete classes; the
        stages that record none fall back to the lot's."""
        lot = self.handover_lot
        return lot.surface_finish if lot else None

    @property
    def received_weight(self):
        """What the previous process handed over - the ceiling for this
        record's own output weight."""
        return self.input_quantity

    @property
    def output_weight(self):
        return self.output_quantity

    # ------------------------------------------------------------------
    # Storage rack zone. Only some processes place their material on a
    # rack (Rolling onto the Forming racks, Finished Goods onto its own);
    # for every other record these resolve to nothing, so one accessor
    # serves every table without asking which process it is looking at.
    # ------------------------------------------------------------------
    @property
    def previous_record(self):
        """The record at the process before this one that handed this lot
        over: the Forming transaction behind a Heat Treatment row.

        This is what lets a process's Main Table carry everything the
        previous process's Complete Table showed - the material arriving
        here *is* that record - without any screen knowing which processes
        exist. Cached per instance, because a table asks every row for it.
        """
        if "_previous_record" in self.__dict__:
            return self.__dict__["_previous_record"]

        from .process_registry import process_for_record

        process = process_for_record(self)
        previous = process.previous if process else None
        lot = self.handover_lot
        record = None
        if previous is not None and lot is not None:
            record = (
                previous.complete_queryset(None)
                .filter(**{previous.handover_lot_path: lot})
                .order_by(previous.handover_ordering)
                .first()
            )
        self.__dict__["_previous_record"] = record
        return record

    @property
    def rack_placement(self):
        from apps.masters import services as rack_services

        from .process_registry import process_for_record

        zone = rack_services.zone_for_process(process_for_record(self))
        return rack_services.open_placement(zone, self.handover_lot)

    @property
    def rack_slot_label(self):
        placement = self.rack_placement
        return placement.slot.label if placement else ""
