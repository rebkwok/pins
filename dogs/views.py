from django.conf import settings
from django.shortcuts import render, HttpResponse
from django.urls import reverse


def facebook_connect(request):
    redirect_uri = reverse("facebook_connect_success")
    url = f"https://www.facebook.com/v18.0/dialog/oauth?client_id={settings.FB_APP_ID}&redirect_uri={redirect_uri}&state=1234"
    return render(request, "facebook_connect.html", {"url": url})


def facebook_connect_success(request):
    return HttpResponse("ok")
