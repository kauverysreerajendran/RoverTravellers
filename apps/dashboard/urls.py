from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardOverviewView.as_view(), name="overview"),
    path("search/", views.global_search, name="search"),
]
