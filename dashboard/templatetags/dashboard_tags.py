from django import template
from wagtail.admin.auth import user_has_any_page_permission

register = template.Library()


@register.filter
def can_edit_pages(user):
    """Whether the user has any page permissions (e.g. so can search pages)"""
    return user_has_any_page_permission(user)
