"""
Basket serializers, used to render the basket in the shop views.

These are in their own module (not shop.serializers) because importing salesman's
basket serializers loads SALESMAN_PRODUCT_TYPES, which imports shop.serializers.
"""
from salesman.basket.serializers import BasketItemSerializer as SalesmanBasketItemSerializer
from salesman.basket.serializers import BasketSerializer as SalesmanBasketSerializer


class BasketItemSerializer(SalesmanBasketItemSerializer):
    """
    Salesman's basket item serializer, without the url to salesman's basket API,
    which isn't exposed (see pins/urls.py)
    """

    url = None

    class Meta(SalesmanBasketItemSerializer.Meta):
        fields = [
            field for field in SalesmanBasketItemSerializer.Meta.fields if field != "url"
        ]
        read_only_fields = fields


class BasketSerializer(SalesmanBasketSerializer):
    items = BasketItemSerializer(source="get_items", many=True, read_only=True)
