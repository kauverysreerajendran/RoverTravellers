from django.urls import path

from . import views

app_name = "forming"

urlpatterns = [
    path("", views.FormingListView.as_view(), name="list"),
    path("create/", views.FormingCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.FormingDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.FormingCompleteView.as_view(), name="complete"),
]
