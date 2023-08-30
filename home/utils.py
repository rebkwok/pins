from django.utils.text import slugify
from wagtail.contrib.forms.utils import get_field_clean_name

def slugify_desc(desc):
    return get_field_clean_name(desc)
