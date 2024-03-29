# Generated by Django 5.0.1 on 2024-02-09 17:40

from django.db import migrations, models


def create_name_and_email(apps, schema_editor):
    PDFFormSubmission = apps.get_model("home", "PDFFormSubmission")

    submissions = PDFFormSubmission.objects.all()
    for submission in submissions:
        submission.name = submission.form_data["name"]
        submission.email = submission.form_data.get("email", submission.form_data.get("email_address"))
        submission.save()


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0026_pdfformfield_after_info_text_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pdfformsubmission',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='pdfformsubmission',
            name='name',
            field=models.CharField(blank=True),
        ),
        migrations.RunPython(create_name_and_email, migrations.RunPython.noop)
    ]
