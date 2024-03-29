# Generated by Django 5.0.1 on 2024-02-12 14:24

import django.core.serializers.json
import encrypted_json_fields.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0027_pdfformsubmission_email_pdfformsubmission_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pdfformsubmission',
            name='email',
            field=encrypted_json_fields.fields.EncryptedEmailField(blank=True),
        ),
        migrations.AlterField(
            model_name='pdfformsubmission',
            name='form_data',
            field=encrypted_json_fields.fields.EncryptedJSONField(encoder=django.core.serializers.json.DjangoJSONEncoder),
        ),
        migrations.AlterField(
            model_name='pdfformsubmission',
            name='name',
            field=encrypted_json_fields.fields.EncryptedCharField(blank=True),
        ),
    ]
