"""Link previews (Open Graph tags), e.g. in Messenger: previewtags.link_preview"""

import re
from types import SimpleNamespace

import pytest
import wagtail_factories
from django.template import Context, Template
from model_bakery import baker
from wagtail.models import Site

from home.models import StandardPage
from home.templatetags.previewtags import page_image
from shop.models import Product

pytestmark = pytest.mark.django_db


def meta(content):
    """The page's meta tags, by property or name"""
    return dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)">', content))


def get_meta(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    return meta(resp.content.decode())


@pytest.fixture(autouse=True)
def served(home_page):
    # Serve the home page from the default site, so pages can be requested
    Site.objects.filter(is_default_site=True).update(root_page=home_page)


@pytest.fixture
def standard_page(home_page):
    page = StandardPage(title="Adopt", introduction="", body="")
    home_page.add_child(instance=page)
    return page


def test_page_without_image(client, home_page):
    # the logo, as a full address (the apps need one), as a small image
    tags = get_meta(client, home_page.url)
    assert tags["og:title"] == "Home"
    assert tags["og:url"] == "http://testserver/"
    assert tags["og:type"] == "website"
    assert tags["og:image"] == "http://testserver/static/images/logo.png"
    assert tags["twitter:card"] == "summary"
    assert "og:image:width" not in tags


def test_page_image(client, standard_page):
    # the page's image, at the size the apps show large images
    standard_page.image = wagtail_factories.ImageFactory(
        title="Podencos", file__width=2000, file__height=1500
    )
    standard_page.save()
    tags = get_meta(client, standard_page.url)
    rendition = standard_page.image.get_rendition("fill-1200x630-c100")
    assert tags["og:image"] == f"http://testserver{rendition.url}"
    assert (tags["og:image:width"], tags["og:image:height"]) == ("1200", "630")
    assert tags["og:image:alt"] == "Podencos"
    assert tags["twitter:card"] == "summary_large_image"


def test_page_description(client, standard_page):
    # the search description; or the page's introduction (or body etc.), as
    # plain text and shortened
    standard_page.introduction = "Meet the dogs\nlooking for homes"
    standard_page.save()
    tags = get_meta(client, standard_page.url)
    assert tags["og:description"] == tags["description"] == "Meet the dogs looking for homes"
    standard_page.introduction = ""
    standard_page.body = "<p>" + "Podencos are lovely. " * 20 + "</p>"
    standard_page.save()
    description = get_meta(client, standard_page.url)["og:description"]
    assert description.startswith("Podencos are lovely. Podencos")
    assert len(description) == 200 and description.endswith("…")
    standard_page.search_description = "Adopt a podenco"
    standard_page.save()
    assert get_meta(client, standard_page.url)["og:description"] == "Adopt a podenco"


def test_page_seo_title(client, standard_page):
    standard_page.seo_title = "Adopt a podenco"
    standard_page.save()
    assert get_meta(client, standard_page.url)["og:title"] == "Adopt a podenco"


def test_no_description(client, standard_page):
    tags = get_meta(client, standard_page.url)
    assert "og:description" not in tags and "description" not in tags


def test_site_name(client, home_page):
    tags = get_meta(client, home_page.url)
    assert tags["og:site_name"] == "Podencos In Need (PINS)"


def test_not_a_page(client, shop_page):
    # e.g. the basket: the site's name
    tags = get_meta(client, "/shop/basket/")
    assert tags["og:title"] == "Podencos In Need (PINS)"
    assert tags["og:image"] == "http://testserver/static/images/logo.png"


def test_product(client, product):
    # the product's name, description and first image
    product.description = "<p>A <b>cosy</b> hoodie</p>"
    product.save()
    image = wagtail_factories.ImageFactory(title="Hoodie")
    baker.make("shop.ProductImage", product=product, image=image)
    baker.make("shop.ProductVariant", product=product, stock=1)
    tags = get_meta(client, product.get_absolute_url())
    assert tags["og:title"] == "Test Product"
    assert tags["og:description"] == "A cosy hoodie"
    assert tags["og:image"] == f"http://testserver{image.get_rendition('fill-1200x630-c100').url}"
    assert tags["og:url"] == f"http://testserver{product.get_absolute_url()}"


def test_product_without_image(client, product, shop_page):
    # the logo (not the shop page's image)
    shop_page.image = wagtail_factories.ImageFactory()
    shop_page.save()
    baker.make("shop.ProductVariant", product=product, stock=1)
    tags = get_meta(client, product.get_absolute_url())
    assert tags["og:image"] == "http://testserver/static/images/logo.png"
    assert "og:description" not in tags


def test_shop_page(client, shop_page):
    shop_page.image = wagtail_factories.ImageFactory()
    shop_page.introduction = "PINS merchandise"
    shop_page.save()
    tags = get_meta(client, shop_page.url)
    assert tags["og:title"] == shop_page.title
    assert tags["og:description"] == "PINS merchandise"
    assert tags["og:image"].endswith(shop_page.image.get_rendition("fill-1200x630-c100").url)


def rendition_url(image):
    return f"http://testserver{image.get_rendition('fill-1200x630-c100').url}"


def test_shop_page_products_image(client, shop_page, category):
    # without its own image: the first image of the first product (in the
    # shop's order) that has one; live products, with live variants
    def make(name, sort_order, live=True, variant_live=True, image=True, variant_image=False):
        product = baker.make(
            "shop.Product", name=name, category=category, sort_order=sort_order, live=live
        )
        variant = baker.make("shop.ProductVariant", product=product, stock=1, live=variant_live)
        if image:
            image = wagtail_factories.ImageFactory()
            baker.make("shop.ProductImage", product=product, image=image)
        if variant_image:
            variant.image = image = wagtail_factories.ImageFactory()
            variant.save()
        return image

    make("Hidden", 0, live=False)
    make("Sold out of all", 1, variant_live=False)
    make("No photos", 2, image=False)
    # (its only image is a hidden variant's)
    make("Hidden variant's photo", 3, image=False)
    baker.make(
        "shop.ProductVariant",
        product=Product.objects.get(name="Hidden variant's photo"),
        variant_name="Hidden",
        live=False,
        image=wagtail_factories.ImageFactory(),
    )
    mug = make("Mug", 4, image=False, variant_image=True)
    make("Card", 5)
    assert get_meta(client, shop_page.url)["og:image"] == rendition_url(mug)
    # its own image, if it has one
    shop_page.image = wagtail_factories.ImageFactory()
    shop_page.save()
    assert get_meta(client, shop_page.url)["og:image"] == rendition_url(shop_page.image)


def test_shop_page_no_products_image(client, shop_page):
    assert get_meta(client, shop_page.url)["og:image"] == "http://testserver/static/images/logo.png"


def test_page_image():
    # the page's image field or method (an auction item's first photo), or a
    # dog's chosen photo
    image = object()
    assert page_image(SimpleNamespace(image=image)) is image
    assert page_image(SimpleNamespace(image=lambda: image)) is image
    assert page_image(SimpleNamespace(cover_image=lambda: image)) is image
    assert page_image(SimpleNamespace(image=None, preview_image=lambda: image)) is image
    assert page_image(SimpleNamespace(image=lambda: None, cover_image=lambda: None)) is None
    assert page_image(SimpleNamespace()) is None


def test_no_request():
    content = Template("{% load previewtags %}{% link_preview %}").render(Context({}))
    assert "<meta" not in content


def test_no_site(rf):
    # (no Wagtail site: no site name)
    Site.objects.all().delete()
    content = Template("{% load previewtags %}{% link_preview %}").render(
        Context({"request": rf.get("/")})
    )
    tags = meta(content)
    assert tags["og:title"] == ""
    assert "og:site_name" not in tags


def test_shop_category(client, shop_page, category):
    # ?category=<slug>: the category's title, description and first photo
    shop_page.introduction = "PINS merchandise"
    shop_page.save()
    mugs = baker.make("shop.Category", title="Mugs", slug="mugs", description="<p>Big mugs</p>")
    for name, product_category in [("Card", category), ("Mug", mugs)]:
        product = baker.make("shop.Product", name=name, category=product_category)
        baker.make("shop.ProductVariant", product=product, stock=1)
        baker.make("shop.ProductImage", product=product, image=wagtail_factories.ImageFactory())
    mug_image = Product.objects.get(name="Mug").images[0].image
    tags = get_meta(client, f"{shop_page.url}?category=mugs")
    assert tags["og:title"] == f"Mugs - {shop_page.title}"
    assert tags["og:description"] == "Big mugs"
    assert tags["og:image"] == rendition_url(mug_image)
    # without a description, or photos: the shop's
    card_image = Product.objects.get(name="Card").images[0].image
    baker.make("shop.Category", title="Empty", slug="empty", description="")
    tags = get_meta(client, f"{shop_page.url}?category=empty")
    assert tags["og:title"] == f"Empty - {shop_page.title}"
    assert tags["og:description"] == "PINS merchandise"
    assert tags["og:image"] == rendition_url(card_image)
    # an unknown category: the shop's preview
    tags = get_meta(client, f"{shop_page.url}?category=nope")
    assert tags["og:title"] == shop_page.title
