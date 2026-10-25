from django.shortcuts import redirect
from django.urls import reverse
from wagtail import hooks
from wagtail.admin.menu import SubmenuMenuItem, admin_menu


# The shop's order pages (menu item names): users whose menu is just these (e.g.
# Orders only users: Orders and Dispatcher activity) start at the first
ORDER_PAGES = {"items-to-send", "orders", "dispatcher-activity"}


def single_admin_page_url(request):
    """
    If the user's admin menu has just one page, or just the shop's order pages
    (e.g. for users who can only see orders), the (first) page's url
    """
    items = admin_menu.menu_items_for_request(request)
    # (as the menu is shown, e.g. without Wagtail's help for some users)
    for hook in hooks.get_hooks("construct_main_menu"):
        hook(request, items)
    if any(isinstance(item, SubmenuMenuItem) for item in items):
        return None
    if len(items) == 1 or (items and all(item.name in ORDER_PAGES for item in items)):
        return items[0].url
    return None


def admin_start_page_middleware(get_response):
    """
    Users whose admin menu has just one page (or just the shop's order pages) go
    straight to it, rather than the admin's welcome page
    """

    def middleware(request):
        if (
            request.method == "GET"
            and request.user.is_authenticated
            and request.path == reverse("wagtailadmin_home")
        ):
            url = single_admin_page_url(request)
            if url:
                return redirect(url)
        return get_response(request)

    return middleware
