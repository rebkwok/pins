from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import pluralize
from django.views.generic import TemplateView
from wagtail.admin import messages
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.views.generic.ordering import ReorderView
from wagtail.log_actions import log
from wagtail.permission_policies import ModelPermissionPolicy

from common.users import real_users_q

from . import activity
from .models import DISPATCHERS_GROUP, Product, dispatcher_name

User = get_user_model()

# The admin menu that the shop's stock, sales, discount codes and dispatchers are in
# The admin menus: what's sold, and the shop's promotions and settings
SHOP_STOCK_MENU_LABEL = "Shop stock"
SHOP_SETUP_MENU_LABEL = "Shop setup"


class CategoryProductsReorderView(ReorderView):
    """
    Move one of a category's products to a new position in the category (from
    the category's page, see models.CategoryProductsPanel)
    """

    model = Product
    sort_order_field = "sort_order"
    permission_policy = ModelPermissionPolicy(Product)

    def get_queryset(self):
        return Product.objects.filter(category_id=self.kwargs["category_pk"]).order_by(
            "sort_order", "name"
        )

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            position = request.GET.get("position")
            log(
                product.category,
                activity.CATEGORY_REORDERED,
                data={
                    "product": product.name,
                    "position": int(position) + 1 if position and position.isdigit() else "",
                },
            )
        return response


class AddDispatcherForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="User",
        empty_label="Choose a user",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(groups__name=DISPATCHERS_GROUP)
            .filter(real_users_q())
            .order_by("first_name", "last_name", "username")
        )
        self.fields["user"].label_from_instance = (
            lambda user: f"{dispatcher_name(user)} ({user.email})"
            if user.email
            else dispatcher_name(user)
        )


class DispatchersView(WagtailAdminTemplateMixin, TemplateView):
    """
    Shop setup > Dispatchers: the users in the Dispatchers group, with their
    products. Site admins (who can change users, and so their groups) can add
    existing users to the group and remove them; people who can edit products
    (e.g. shop admins, who choose products' dispatchers) can see who they are.
    """

    template_name = "shop/admin/dispatchers.html"
    page_title = "Dispatchers"
    header_icon = "group"

    # (changing a user's groups needs permission to change users)
    manage_permission = "auth.change_user"
    view_permission = "shop.change_product"

    @classmethod
    def can_view(cls, user):
        return user.has_perm(cls.manage_permission) or user.has_perm(cls.view_permission)

    @property
    def can_manage(self):
        return self.request.user.has_perm(self.manage_permission)

    def dispatch(self, request, *args, **kwargs):
        if not self.can_view(request.user):
            raise PermissionDenied
        if request.method == "POST" and not self.can_manage:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": None, "label": SHOP_SETUP_MENU_LABEL},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dispatchers"] = (
            User.objects.filter(real_users_q(), groups__name=DISPATCHERS_GROUP)
            .prefetch_related(
                Prefetch(
                    "dispatched_products",
                    queryset=Product.objects.select_related("category").order_by(
                        "category__sort_order", "category__title", "sort_order", "name"
                    ),
                )
            )
            .order_by("first_name", "last_name", "username")
        )
        context["can_manage"] = self.can_manage
        if self.can_manage:
            context["form"] = kwargs.get("form") or AddDispatcherForm()
        return context

    def post(self, request, *args, **kwargs):
        group = Group.objects.get(name=DISPATCHERS_GROUP)
        if "remove" in request.POST:
            user = get_object_or_404(User, pk=request.POST["remove"], groups=group)
            user.groups.remove(group)
            log(user, activity.DISPATCHER_REMOVED)
            message = f"{dispatcher_name(user)} isn't a dispatcher any more."
            product_count = user.dispatched_products.count()
            if product_count:
                message += (
                    f" {product_count} product{pluralize(product_count)} still "
                    f"{pluralize(product_count, 'has,have')} them as dispatcher: "
                    "choose another dispatcher for "
                    f"{pluralize(product_count, 'it,them')}."
                )
                messages.warning(request, message)
            else:
                messages.success(request, message)
            return redirect("shop_dispatchers:index")
        form = AddDispatcherForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        user = form.cleaned_data["user"]
        user.groups.add(group)
        log(user, activity.DISPATCHER_ADDED)
        messages.success(request, f"{dispatcher_name(user)} is now a dispatcher.")
        return redirect("shop_dispatchers:index")
