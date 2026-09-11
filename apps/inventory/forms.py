from apps.master_data.forms import StyledModelForm

from . import models


class StockTransferForm(StyledModelForm):
    class Meta:
        model = models.StockTransfer
        fields = ["stock_type", "material", "lot", "from_location", "to_location", "quantity", "remarks"]


class StockAdjustmentForm(StyledModelForm):
    class Meta:
        model = models.StockAdjustment
        fields = ["stock_type", "material", "lot", "location", "quantity_after", "reason", "remarks"]
