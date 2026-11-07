"""
Link previews (Open Graph tags): what Messenger, WhatsApp, Facebook etc. show
for a link to a page
"""

from django import template
from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.text import Truncator
from wagtail.models import Site

register = template.Library()

# A page's description, if it has no search description: the first of these
# it has, as plain text
DESCRIPTION_FIELDS = ["introduction", "short_description", "intro", "description", "body"]
DESCRIPTION_LENGTH = 200
# The size the apps show a large image at
IMAGE_SPEC = "fill-1200x630-c100"
LOGO = "images/logo.png"


def plain_text(text):
    text = " ".join(strip_tags(str(text or "")).split())
    return Truncator(text).chars(DESCRIPTION_LENGTH)


def page_description(page):
    if page.search_description:
        return page.search_description
    for field in DESCRIPTION_FIELDS:
        text = plain_text(getattr(page, field, ""))
        if text:
            return text
    return ""


def page_image(page):
    """
    The page's image: its image field, or method (e.g. an auction item's first
    photo); or a dog's chosen photo; or one for previews (e.g. the shop page's,
    from its products)
    """
    for name in ["image", "cover_image", "preview_image"]:
        image = getattr(page, name, None)
        if callable(image):
            image = image()
        if image is not None:
            return image
    return None


def site_name(request):
    if Site.find_for_request(request) is None:
        return ""
    from dashboard.models import SiteSettings

    # (cached on the request, as for the page's title)
    return SiteSettings.for_request(request).title_suffix.strip(" |")


@register.inclusion_tag("home/includes/link_preview.html", takes_context=True)
def link_preview(context, title=None, description=None, image=None):
    """
    The page's preview: its title, description and image, or those given (e.g.
    a product's, which isn't a page; a blank image, e.g. a product without
    any, is the logo, not the page's). The image defaults to the logo.
    """
    request = context.get("request")
    if request is None:
        return {"preview": None}
    page = context.get("page")
    name = site_name(request)
    # (a Wagtail page: not e.g. a paginator's page)
    if page is not None and hasattr(page, "search_description"):
        title = title or page.seo_title or page.title
        if description is None:
            description = page_description(page)
        if image is None:
            image = page_image(page)
    preview = {
        "url": request.build_absolute_uri(),
        "title": title or name,
        "description": plain_text(description),
        "site_name": name,
    }
    if image:
        rendition = image.get_rendition(IMAGE_SPEC)
        preview.update(
            image=request.build_absolute_uri(rendition.url),
            image_width=rendition.width,
            image_height=rendition.height,
            image_alt=rendition.alt,
            large_image=True,
        )
    else:
        preview["image"] = request.build_absolute_uri(static(LOGO))
    return {"preview": preview}
