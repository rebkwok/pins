import os


def home(request):
    return {
        "hide_search": os.environ.get("HIDE_SEARCH", False),
        "hide_breadcrumbs": os.environ.get("HIDE_BREADCRUMBS", False),
    }
