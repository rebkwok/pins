from django.conf import settings
from django.urls import include, path
from django.contrib import admin

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from search import views as search_views
from home import orders_urls
from home import views as home_views
from fundraising import urls

urlpatterns = [
    path("", include('allauth.urls')),
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("search/", search_views.search, name="search"),
    path("orders/", include(orders_urls)),
    path("fundraising/", include(urls)),
    path('paypal/', include("paypal.standard.ipn.urls")),
    path("payments/", include("payments.urls")),
    path(
        "submitted-form/<str:reference>/access-request/", 
        home_views.pdf_form_token_request, 
        name="pdf_form_token_request"
    ),
    path(
        "submitted-form/<str:reference>/", 
        home_views.pdf_form_detail, 
        name="pdf_form_detail"
    ),
    path(
        "submitted-form/<int:pk>/download/", 
        home_views.pdf_form_download, 
        name="pdf_form_download"
    ),
    path(
        "merchandise-information/",
        home_views.merch_info,
        name="merch_info"
    )
]


if settings.DEBUG or settings.TESTING:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += (path(r'django-admin/django-ses/', include('django_ses.urls')),)

urlpatterns = urlpatterns + [
    # For anything not caught by a more specific rule above, hand over to
    # Wagtail's page serving mechanism. This should be the last pattern in
    # the list:
    path("", include(wagtail_urls)),
    # Alternatively, if you want Wagtail pages to be served from a subpath
    # of your site, rather than the site root:
    #    path("pages/", include(wagtail_urls)),
]
