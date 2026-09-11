from django.urls import path

from . import views

app_name = "finishing"

urlpatterns = [
    path("", views.FinishingListView.as_view(), name="list"),
    path("create/", views.FinishingCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.FinishingDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.FinishingCompleteView.as_view(), name="complete"),
]
