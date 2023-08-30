from django import template

register = template.Library()
# https://docs.djangoproject.com/en/3.2/howto/custom-template-tags/


@register.filter
def is_order_quantity(page, field_label):
    return field_label in page.product_variant_descriptions()


@register.simple_tag
def get_product_variant(page, field_label):
    return page.product_variants.get(description=field_label)

