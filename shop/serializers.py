# serializers.py
from rest_framework import serializers

from . import models


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ProductVariant
        fields = ["name", "code"]

