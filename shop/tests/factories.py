import wagtail_factories

from ..models import CategoryPage, ShopPage



class CategoryPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = CategoryPage


class ShopPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = ShopPage


# Product admin form data that most tests don't set: no images, and no shared
# stock
PRODUCT_FORM_DEFAULTS = {
    "product_images-TOTAL_FORMS": "0",
    "product_images-INITIAL_FORMS": "0",
    "product_images-MIN_NUM_FORMS": "0",
    "product_images-MAX_NUM_FORMS": "1000",
    "stock": "0",
}

# The connected Stripe account in the tests (see conftest)
STRIPE_ACCOUNT = "acct_shop_test"
