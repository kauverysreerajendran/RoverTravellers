from django.urls import path

from . import views

app_name = "rolling"

urlpatterns = [
    path("", views.RollingListView.as_view(), name="list"),
    path("create/", views.RollingCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.RollingDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.RollingCompleteView.as_view(), name="complete"),
]
