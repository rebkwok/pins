from django import template
from wagtail.models import Page, Site

from home.models import FooterText

register = template.Library()


@register.inclusion_tag("home/includes/standard_page_button.html", takes_context=True)
def standard_page_button(context, location):
    page = context["page"]
    if not page.button_text:
        return {"show_button": False}
    
    if page.button_display == "both" or page.button_display == location:
        return {"page": page, "show_button": True}

    return {"show_button": False}
