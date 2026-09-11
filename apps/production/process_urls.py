from django.urls import path

from .process_views import ProcessCompleteTableView, ProcessMainTableView

app_name = "process"

urlpatterns = [
    path("<slug:process>/main/", ProcessMainTableView.as_view(), name="main"),
    path("<slug:process>/complete/", ProcessCompleteTableView.as_view(), name="complete"),
]
