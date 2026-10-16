from django.conf import settings


def home(request):
    return {
        "hide_search": settings.HIDE_SEARCH,
        "hide_breadcrumbs": settings.HIDE_BREADCRUMBS,
    }
