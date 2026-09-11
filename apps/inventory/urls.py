from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("raw-material/", views.RawMaterialStockListView.as_view(), name="raw_material_list"),
    path("wip/", views.WIPStockListView.as_view(), name="wip_list"),
    path("finished-goods/", views.FinishedGoodsStockListView.as_view(), name="finished_goods_list"),
    path("transactions/", views.StockTransactionListView.as_view(), name="transaction_list"),
    path("transfers/", views.StockTransferListView.as_view(), name="transfer_list"),
    path("transfers/create/", views.StockTransferCreateView.as_view(), name="transfer_create"),
    path("transfers/<uuid:pk>/complete/", views.StockTransferCompleteView.as_view(), name="transfer_complete"),
    path("adjustments/", views.StockAdjustmentListView.as_view(), name="adjustment_list"),
    path("adjustments/create/", views.StockAdjustmentCreateView.as_view(), name="adjustment_create"),
]
