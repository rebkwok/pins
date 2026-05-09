from django.db import migrations, models


def consolidate_to_singleton(apps, schema_editor):
    FacebookAlbums = apps.get_model("dogs", "FacebookAlbums")
    rows = list(FacebookAlbums.objects.order_by("-id"))
    if not rows:
        return
    latest = rows[0]
    if latest.pk != 1:
        FacebookAlbums.objects.filter(pk=latest.pk).update(id=1)
    FacebookAlbums.objects.exclude(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dogs", "0014_alter_dogpagegalleryimage_options"),
    ]

    operations = [
        migrations.RunPython(consolidate_to_singleton, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="facebookalbums",
            old_name="previous_albums",
            new_name="reporting_baseline",
        ),
        migrations.AddField(
            model_name="facebookalbums",
            name="pending_site_changes",
            field=models.JSONField(default=dict),
        ),
    ]
