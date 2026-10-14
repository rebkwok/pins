from salesman.admin.wagtail.panels import ReadOnlyPanel
from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.core.utils import get_salesman_model
from wagtail.admin.ui.tables import BooleanColumn
from wagtail_modeladmin.options import modeladmin_register
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import Product, ProductVariant, Sale, SaleCategory, SaleProduct


Order = get_salesman_model("Order")


class ProductViewSet(SnippetViewSet):
    model = Product
    list_display = (
        "name",
        "category_link",
        "index",
        BooleanColumn("live"),
        "get_variant_count",
    )
    list_filter = ("category_page",)


class ProductVariantViewSet(SnippetViewSet):
    model = ProductVariant
    list_display = (
        "product",
        "variant_full_name",
        "category_link",
        "price",
        "stock",
        BooleanColumn("live"),
    )
    list_filter = ("product",)


class SaleViewSet(SnippetViewSet):
    model = Sale
    list_display = (
        "name",
        "start_date",
        "end_date",
    )


class ProductGroup(SnippetViewSetGroup):
    menu_label = "Shop Stock"
    menu_icon = "pick"
    items = (ProductViewSet, ProductVariantViewSet, SaleViewSet)
    menu_order = 200


class OrderAdmin(SalesmanOrderAdmin):
    SalesmanOrderAdmin.list_display.insert(2, "name")
    SalesmanOrderAdmin.list_display.insert(4, "shipping_method")
    SalesmanOrderAdmin.search_fields.append("name")
    SalesmanOrderAdmin.default_panels[2].children.insert(2, ReadOnlyPanel("name"))
    SalesmanOrderAdmin.default_panels[2].children.insert(
        3, ReadOnlyPanel("shipping_method")
    )
    menu_order = 250


register_snippet(ProductGroup)
modeladmin_register(OrderAdmin)
