from salesman.core.utils import get_salesman_model

Basket = get_salesman_model("Basket")


def clear_expired_baskets_middleware(get_response):
    # One-time configuration and initialization.

    def middleware(request):
        # Clear expired baskets before any non-htmx view is called
        if "Hx-Request" not in request.headers:
            Basket.clear_expired()
        response = get_response(request)
        return response

    return middleware
