from django.urls import include, path
from payments.views import payment_cancel, paypal_return


app_name = 'payments'

urlpatterns = [
    path('confirm/', paypal_return,
        name='paypal_return'),
    path('cancel/', payment_cancel,
        name='paypal_cancel'),
    ]