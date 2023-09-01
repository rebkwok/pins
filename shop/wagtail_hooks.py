from django.urls import reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from wagtail.admin.userbar import AccessibilityItem
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import ProductCategory, Product, ProductVariant


class ProductCategoryViewSet(SnippetViewSet):
    model = ProductCategory
    list_display = ("name",)


class ProductViewSet(SnippetViewSet):
    model = Product
    list_display = ("name",)
    list_filter = ("category",)


class ProductVariantViewSet(SnippetViewSet):
    model = ProductVariant
    list_display = ("product", "name", "category", "price")
    list_filter = ("product",)
    fields = ("product", "name", "price")
    

class ProductGroup(SnippetViewSetGroup):
    menu_label = "Products" 
    menu_icon = "pick"
    items = (ProductCategoryViewSet, ProductViewSet, ProductVariantViewSet)


class ProductVariantViewSet(SnippetViewSet):
    model = ProductVariant
    list_display = ("product", "name", "category", "price")
    list_filter = ("product",)
    fields = ("product", "name", "price")


register_snippet(ProductGroup)
