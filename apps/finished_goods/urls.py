from django.urls import path

from . import views

app_name = "finished_goods"

urlpatterns = [
    path("", views.FinishedGoodsListView.as_view(), name="list"),
    path("receive/", views.FinishedGoodsReceiveView.as_view(), name="receive"),
    path("<uuid:pk>/", views.FinishedGoodsDetailView.as_view(), name="detail"),
    path("<uuid:pk>/approve/", views.FinishedGoodsApproveView.as_view(), name="approve"),
    path("<uuid:pk>/reject/", views.FinishedGoodsRejectView.as_view(), name="reject"),
    path("<uuid:pk>/hold/", views.FinishedGoodsHoldView.as_view(), name="hold"),
]
