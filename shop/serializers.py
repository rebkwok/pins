# serializers.py
from rest_framework import serializers
from salesman.core.utils import get_salesman_model
from salesman.orders.serializers import OrderSerializer as SalesmanOrderSerializer

from . import models


Order = get_salesman_model("Order")


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ProductVariant
        fields = ["name", "code"]


class OrderSerializer(SalesmanOrderSerializer):
    class Meta(SalesmanOrderSerializer.Meta):
        SalesmanOrderSerializer.Meta.fields.insert(11, "name")
