from django.shortcuts import redirect
from django.urls import reverse
from wagtail import hooks
from wagtail.admin.menu import SubmenuMenuItem, admin_menu


def single_admin_page_url(request):
    """
    If the user's admin menu has just one page (e.g. Orders, for users who can
    only see orders), its url
    """
    items = admin_menu.menu_items_for_request(request)
    # (as the menu is shown, e.g. without Wagtail's help for some users)
    for hook in hooks.get_hooks("construct_main_menu"):
        hook(request, items)
    if len(items) == 1 and not isinstance(items[0], SubmenuMenuItem):
        return items[0].url
    return None


def admin_start_page_middleware(get_response):
    """
    Users whose admin menu has just one page go straight to it, rather than the
    admin's welcome page
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
