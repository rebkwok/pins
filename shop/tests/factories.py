import wagtail_factories

from ..models import CategoryPage, ShopPage



class CategoryPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = CategoryPage


class ShopPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = ShopPage


# The product admin form's images formset, with no images
NO_PRODUCT_IMAGES = {
    "product_images-TOTAL_FORMS": "0",
    "product_images-INITIAL_FORMS": "0",
    "product_images-MIN_NUM_FORMS": "0",
    "product_images-MAX_NUM_FORMS": "1000",
}

# The connected Stripe account in the tests (see conftest)
STRIPE_ACCOUNT = "acct_shop_test"
