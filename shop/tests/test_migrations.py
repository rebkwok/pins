"""Data migrations"""
import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F

LATEST = [("shop", "0016_delete_categorypage")]


def migrate(targets):
    """Migrate to targets, returning the historical models"""
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def root_page():
    # (replaces conftest's autouse root page: these tests make their own pages,
    # with the historical models, and transactional tests flush the database,
    # including the default locale that the root page needs)
    yield None


@pytest.fixture
def migrations():
    """Migrate back to the latest migrations afterwards"""
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    yield migrate
    migrate(leaf_nodes)


def add_page(apps, parent, model_name, **fields):
    """
    Add a page under parent with the historical models (which don't have
    treebeard's methods, e.g. add_child)
    """
    Page = apps.get_model("wagtailcore", "Page")
    model = apps.get_model("shop", model_name)
    content_type = ContentType.objects.get_for_model(model)
    numchild = Page.objects.filter(
        path__startswith=parent.path, depth=parent.depth + 1
    ).count()
    page = model.objects.create(
        path=f"{parent.path}{numchild + 1:04d}",
        depth=parent.depth + 1,
        numchild=0,
        content_type_id=content_type.id,
        locale_id=parent.locale_id,
        url_path=f"{parent.url_path}{fields['slug']}/",
        draft_title=fields["title"],
        live=True,
        **fields,
    )
    Page.objects.filter(pk=parent.pk).update(numchild=F("numchild") + 1)
    return page


def shop_page(apps):
    Page = apps.get_model("wagtailcore", "Page")
    # (the tree's root page may have been flushed by other tests)
    root = Page.objects.filter(depth=1).first() or Page.objects.create(
        title="Root",
        slug="root",
        path="0001",
        depth=1,
        numchild=0,
        url_path="/",
        locale_id=apps.get_model("wagtailcore", "Locale").objects.get_or_create(
            language_code="en"
        )[0].id,
        content_type_id=ContentType.objects.get_for_model(Page).id,
    )
    return add_page(apps, root, "ShopPage", title="Shop", slug="shop")


@pytest.mark.django_db(transaction=True)
def test_product_images_migration(migrations):
    apps = migrations([("shop", "0006_shipping_method_default_delivery")])
    Image = apps.get_model("wagtailimages", "Image")
    Product = apps.get_model("shop", "Product")
    category_page = add_page(apps, shop_page(apps), "CategoryPage", title="Cards", slug="cards")
    image = Image.objects.create(title="Mug", file="mug.jpg", width=10, height=10)
    with_image = Product.objects.create(
        category_page=category_page, name="Mug", price=1, image=image
    )
    without_image = Product.objects.create(category_page=category_page, name="Card", price=1)

    # forwards: the product's image becomes its first product image
    apps = migrations([("shop", "0007_product_images")])
    ProductImage = apps.get_model("shop", "ProductImage")
    assert list(
        ProductImage.objects.values_list("product_id", "image_id", "sort_order")
    ) == [(with_image.id, image.id, 0)]

    # backwards: the first product image becomes the product's image
    ProductImage.objects.create(
        product_id=with_image.id,
        image=apps.get_model("wagtailimages", "Image").objects.create(
            title="Mug 2", file="mug2.jpg", width=10, height=10
        ),
        sort_order=1,
    )
    apps = migrations([("shop", "0006_shipping_method_default_delivery")])
    Product = apps.get_model("shop", "Product")
    assert Product.objects.get(id=with_image.id).image_id == image.id
    assert Product.objects.get(id=without_image.id).image_id is None
    # (back to the latest, with no products whose categories aren't migrated)
    Product.objects.all().delete()


@pytest.mark.django_db(transaction=True)
def test_categories_migration(migrations):
    apps = migrations([("shop", "0013_item_not_sent_status")])
    Product = apps.get_model("shop", "Product")
    Sale = apps.get_model("shop", "Sale")
    SaleCategory = apps.get_model("shop", "SaleCategory")
    shop = shop_page(apps)
    # (in their shop page order, "index")
    mugs = add_page(apps, shop, "CategoryPage", title="Mugs", slug="mugs", index=2, body="<p>Mugs</p>")
    cards = add_page(apps, shop, "CategoryPage", title="Cards", slug="cards", index=1)
    # categories from another shop page, with the same title and slug
    other_shop = shop_page(apps)
    other_cards = add_page(apps, other_shop, "CategoryPage", title="Cards", slug="cards", index=3)
    mug = Product.objects.create(category_page=mugs, name="Mug", price=10)
    card = Product.objects.create(category_page=cards, name="Card", price=2)
    other_card = Product.objects.create(category_page=other_cards, name="Card", price=2)
    sale = Sale.objects.create(name="Sale", start_date="2026-01-01", end_date="2026-01-02")
    SaleCategory.objects.create(sale=sale, category=mugs, discount=10)

    apps = migrations(LATEST)
    Category = apps.get_model("shop", "Category")
    Page = apps.get_model("wagtailcore", "Page")
    Product = apps.get_model("shop", "Product")
    assert list(Category.objects.values_list("title", "slug", "sort_order")) == [
        ("Cards", "cards", 0),
        ("Mugs", "mugs", 1),
        ("Cards 2", "cards-2", 2),
    ]
    assert Category.objects.get(slug="mugs").description == "<p>Mugs</p>"
    assert Product.objects.get(id=mug.id).category.slug == "mugs"
    assert Product.objects.get(id=card.id).category.slug == "cards"
    assert Product.objects.get(id=other_card.id).category.slug == "cards-2"
    sale_category = apps.get_model("shop", "SaleCategory").objects.get()
    assert sale_category.category.slug == "mugs"
    # the category pages have gone, and the shop pages' child counts are right
    assert not Page.objects.filter(id__in=[mugs.id, cards.id, other_cards.id]).exists()
    assert Page.objects.get(id=shop.id).numchild == 0
    assert Page.objects.get(id=other_shop.id).numchild == 0



@pytest.mark.django_db(transaction=True)
def test_categories_migration_category_page_with_children(migrations):
    # a category page's child pages would be deleted, so the migration stops
    apps = migrations([("shop", "0013_item_not_sent_status")])
    cards = add_page(apps, shop_page(apps), "CategoryPage", title="Cards", slug="cards", index=1)
    add_page(apps, cards, "ShopPage", title="Card sizes", slug="sizes")
    with pytest.raises(RuntimeError, match="These category pages have child pages"):
        migrations(LATEST)
    apps = migrations([("shop", "0013_item_not_sent_status")])
    apps.get_model("wagtailcore", "Page").objects.filter(depth__gt=1).delete()


@pytest.mark.django_db(transaction=True)
def test_shop_groups_migration(migrations):
    apps = migrations([("shop", "0016_delete_categorypage")])
    Collection = apps.get_model("wagtailcore", "Collection")
    Image = apps.get_model("wagtailimages", "Image")
    # (the root collection may have been flushed by other tests)
    root = Collection.objects.filter(depth=1).first() or Collection.objects.create(
        name="Root", path="0001", depth=1, numchild=0
    )
    # (and the Shop collection may be left from migrating back past 0017)
    Collection.objects.filter(depth__gt=1).delete()
    events = Collection.objects.create(
        name="Events", path=root.path + "0001", depth=2, numchild=0
    )
    Collection.objects.filter(pk=root.pk).update(numchild=1)

    def image(title, collection):
        return Image.objects.create(
            title=title, file=f"{title}.jpg", width=10, height=10, collection=collection
        )

    product_image, variant_image = image("mug", root), image("mug-blue", root)
    filed, unused = image("event", events), image("dog", root)
    category = apps.get_model("shop", "Category").objects.create(title="Mugs", slug="mugs")
    product = apps.get_model("shop", "Product").objects.create(
        category=category, name="Mug", price=10
    )
    ProductImage = apps.get_model("shop", "ProductImage")
    ProductImage.objects.create(product=product, image=product_image, sort_order=0)
    ProductImage.objects.create(product=product, image=filed, sort_order=1)
    apps.get_model("shop", "ProductVariant").objects.create(
        product=product, variant_name="Blue", image=variant_image, sort_order=0
    )

    apps = migrations(LATEST + [("shop", "0017_shop_groups")])
    Collection = apps.get_model("wagtailcore", "Collection")
    Image = apps.get_model("wagtailimages", "Image")
    shop = Collection.objects.get(name="Shop")
    assert (shop.depth, shop.path) == (2, root.path + "0002")
    assert Collection.objects.get(pk=root.pk).numchild == 2
    # the shop's images in the root collection are moved; others aren't
    assert Image.objects.get(pk=product_image.pk).collection_id == shop.pk
    assert Image.objects.get(pk=variant_image.pk).collection_id == shop.pk
    assert Image.objects.get(pk=filed.pk).collection_id == events.pk
    assert Image.objects.get(pk=unused.pk).collection_id == root.pk
    # shop admins' image permissions are in the Shop collection
    group = apps.get_model("auth", "Group").objects.get(name="Shop admins")
    assert set(
        apps.get_model("wagtailcore", "GroupCollectionPermission")
        .objects.filter(group=group)
        .values_list("collection_id", flat=True)
    ) == {shop.pk}
