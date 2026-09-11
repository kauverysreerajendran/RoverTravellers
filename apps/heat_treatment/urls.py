from django.urls import path

from . import views

app_name = "heat_treatment"

urlpatterns = [
    path("", views.HeatTreatmentListView.as_view(), name="list"),
    path("create/", views.HeatTreatmentCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.HeatTreatmentDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.HeatTreatmentCompleteView.as_view(), name="complete"),
]
