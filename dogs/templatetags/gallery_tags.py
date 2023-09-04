from django import template


register = template.Library()


# Retrieves a single gallery item and returns a gallery of images
@register.inclusion_tag("dogs/tags/gallery.html", takes_context=True)
def gallery(context, gallery_images):
    return {
        "images": gallery_images,
        "request": context["request"],
    }
