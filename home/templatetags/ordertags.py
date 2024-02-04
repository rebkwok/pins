from django import template

register = template.Library()
# https://docs.djangoproject.com/en/3.2/howto/custom-template-tags/


@register.filter
def is_order_quantity(page, field_name):
    return field_name in page.product_quantity_field_names


@register.simple_tag
def get_product_variant(page, field_name):
    return page.product_variants.get(slug=field_name)


@register.filter
def is_end_of_form_field(page, field_name):
    return field_name in page.end_of_form_field_names


@register.simple_tag
def get_variant_form_field(form, field_name):
    for field in form:
        if field.name == field_name:
            return field
