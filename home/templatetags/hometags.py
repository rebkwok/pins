from django import template

from django.utils.safestring import mark_safe

register = template.Library()


@register.inclusion_tag("home/includes/standard_page_button.html", takes_context=True)
def standard_page_button(context, location):
    page = context["page"]
    if not page.button_text:
        return {"show_button": False}
    
    if page.button_display == "both" or page.button_display == location:
        return {"page": page, "show_button": True}

    return {"show_button": False}


@register.simple_tag(takes_context=True)
def get_info_text(context, field_name, location):
    page = context["page"]
    if field_name in page.form_field_info_texts:
        return mark_safe(page.form_field_info_texts[field_name][location])
    return ""
