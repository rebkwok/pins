from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from home import orders_urls
from home import views as home_views
from fundraising import urls
from salesman.checkout.payment import payment_methods_pool
from search import views as search_views
from shop import urls as shop_urls
from shop.payment import stripe_webhook_view


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
    ),
    path("shop/", include(shop_urls)),
    path("stripe/webhook/", stripe_webhook_view, name="shop-stripe-webhook"),
    # Only the payment urls (e.g. stripe success, cancel and webhook) from salesman;
    # its basket, checkout and orders API would bypass the shop views' checks
    # (stock, live products, basket locked during payment)
    path("api/", include(payment_methods_pool.get_urls())),
]


if settings.DEBUG or settings.TESTING:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += (path(r"django-admin/django-ses/", include("django_ses.urls")),)


urlpatterns = urlpatterns + [
    # For anything not caught by a more specific rule above, hand over to
    # Wagtail's page serving mechanism. This should be the last pattern in
    # the list:
    path("", include(wagtail_urls)),
    # Alternatively, if you want Wagtail pages to be served from a subpath
    # of your site, rather than the site root:
    #    path("pages/", include(wagtail_urls)),
]
