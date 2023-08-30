import os


def home(request):
    return {
        "hide_search": os.environ.get("HIDE_SEARCH", False)
    }
