from django.urls import path

from .view_as import stop_view_as

urlpatterns = [
    path("stop/", stop_view_as, name="stop_view_as"),
]
