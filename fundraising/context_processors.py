from django.conf import settings
from .models import RecipeBookSubmission, PAGE_TYPE_PAGE_COUNTS


def recipes(request):
    return {
        "total_recipe_book_pages": sum([PAGE_TYPE_PAGE_COUNTS[subm.page_type] for subm in RecipeBookSubmission.objects.all()]),
        "total_recipe_book_money": sum([subm.cost for subm in RecipeBookSubmission.objects.all()]),
        "total_recipe_book_pending": sum([subm.cost for subm in RecipeBookSubmission.objects.filter(paid=False)]) ,
        "recipe_submissions_open": settings.RECIPE_SUBMISSIONS_OPEN,
    }
