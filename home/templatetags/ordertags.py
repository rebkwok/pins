from django import template

register = template.Library()
# https://docs.djangoproject.com/en/3.2/howto/custom-template-tags/


@register.filter
def is_order_quantity(field_name):
    return field_name.startswith("quantity_")


@register.simple_tag
def get_product_variant(page, field_name):
    variant_index = int(field_name.split("_")[-1]) - 1
    variants = page.product_variants.all()
    return variants[variant_index]


@register.filter
def get_total(page, request):
    data = {key: value.initial for key, value in form.fields.items()}
    _, total = page.get_variant_quantities_and_total(data)
    total= 0
    return total
