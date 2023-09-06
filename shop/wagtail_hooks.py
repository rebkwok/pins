from salesman.admin.wagtail.panels import ReadOnlyPanel
from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.core.utils import get_salesman_model
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.contrib.modeladmin.options import modeladmin_register
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import Product, ProductCategory, ProductVariant


Order = get_salesman_model("Order")


class ProductCategoryViewSet(SnippetViewSet):
    model = ProductCategory
    list_display = ("name", "index", BooleanColumn("live"), "get_product_count")
    list_editable = ("index", "live")


class ProductViewSet(SnippetViewSet):
    model = Product
    list_display = (
        "name",
        "category",
        "index",
        BooleanColumn("live"),
        "get_variant_count",
    )
    list_filter = ("category",)


class ProductVariantViewSet(SnippetViewSet):
    model = ProductVariant
    list_display = ("product", "name", "get_category", "price", BooleanColumn("live"))
    list_filter = ("product",)


class ProductGroup(SnippetViewSetGroup):
    menu_label = "Shop Stock"
    menu_icon = "pick"
    items = (ProductCategoryViewSet, ProductViewSet, ProductVariantViewSet)


class OrderAdmin(SalesmanOrderAdmin):
    SalesmanOrderAdmin.list_display.insert(2, "name")
    SalesmanOrderAdmin.search_fields.append("name")
    SalesmanOrderAdmin.default_panels[2].children.insert(2, ReadOnlyPanel("name"))


register_snippet(ProductGroup)
modeladmin_register(OrderAdmin)
