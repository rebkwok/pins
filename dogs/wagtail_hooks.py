from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.auth import permission_required

from common.admin_menu import PermissionMenuItem

from dogs.models import DogPage, DogStatusPage, FacebookAlbums


FACEBOOK_CHANGES_PERMISSION = "dogs.review_facebook_changes"


class FacebookChangesMenuItem(PermissionMenuItem):
    """Facebook Changes, with a dot when there are changes to review"""

    def render_component(self, request):
        # (checked for each request; the menu items are only created once)
        changes = FacebookAlbums.instance().pending_changes()
        self.classname = "facebook-changes-pending" if any(changes.values()) else ""
        return super().render_component(request)


@hooks.register('register_admin_menu_item')
def register_facebook_changes_menu_item():
    return FacebookChangesMenuItem(
        'Facebook Changes',
        reverse('facebook_changes'),
        icon_name='image',
        # (after Footer Text, see dashboard/wagtail_hooks.py)
        order=460,
        permission=FACEBOOK_CHANGES_PERMISSION,
    )


@hooks.register('insert_global_admin_css')
def facebook_changes_admin_css():
    return mark_safe("""
    <style>
    .facebook-changes-pending .menuitem-label::after {
        content: "";
        display: inline-block;
        width: 8px;
        height: 8px;
        background-color: #e74c3c;
        border-radius: 50%;
        margin-inline-start: 6px;
        vertical-align: middle;
    }
    </style>
    """)


@hooks.register('register_admin_urls')
def register_facebook_admin_urls():
    return [
        path('facebook-changes/', facebook_changes_view, name='facebook_changes'),
        path('facebook-changes/acknowledge/', facebook_acknowledge_view, name='facebook_acknowledge'),
    ]


def _enrich_changes(changes):
    all_album_ids = (
        list(changes.get('added', {}).keys())
        + list(changes.get('removed', {}).keys())
        + list(changes.get('changed', {}).keys())
        + list(changes.get('moved', {}).keys())
        + list(changes.get('changed_and_moved', {}).keys())
        + list(changes.get('recreated', {}).keys())
    )
    dog_pages = DogPage.objects.filter(facebook_album_id__in=all_album_ids).only(
        'facebook_album_id', 'pk', 'title', 'path'
    )
    pages_by_album = {page.facebook_album_id: page for page in dog_pages}

    parent_paths = {page.path[:-4] for page in dog_pages}
    status_pages = DogStatusPage.objects.filter(path__in=parent_paths).only('path', 'pk', 'title')
    status_by_path = {p.path: p for p in status_pages}

    def with_page(album_id):
        page = pages_by_album.get(album_id)
        status = status_by_path.get(page.path[:-4]) if page else None
        return page, status

    result = {}
    for section in ('added', 'removed', 'changed'):
        result[section] = [
            (album_id, description, *with_page(album_id))
            for album_id, description in changes.get(section, {}).items()
        ]
    # moved: val = {"album_name": ..., "page_title": ..., "from": ..., "to": ...}
    result['moved'] = [
        (album_id, val['album_name'], val['page_title'], val['from'], val['to'], *with_page(album_id))
        for album_id, val in changes.get('moved', {}).items()
    ]
    # changed_and_moved: val = {"description": ..., "page_title": ..., "from": ..., "to": ...}
    result['changed_and_moved'] = [
        (album_id, val['description'], val['page_title'], val['from'], val['to'], *with_page(album_id))
        for album_id, val in changes.get('changed_and_moved', {}).items()
    ]
    # recreated: val = {"page_title": ..., "facebook_album_name": ...}
    result['recreated'] = [
        (album_id, val['facebook_album_name'], val['page_title'], *with_page(album_id))
        for album_id, val in changes.get('recreated', {}).items()
    ]
    return result


@permission_required(FACEBOOK_CHANGES_PERMISSION)
def facebook_changes_view(request):
    albums_obj = FacebookAlbums.instance()
    changes = albums_obj.pending_changes()
    has_changes = any(changes.values())
    return render(request, 'dogs/facebook_changes.html', {
        'changes': _enrich_changes(changes),
        'has_changes': has_changes,
    })


@permission_required(FACEBOOK_CHANGES_PERMISSION)
def facebook_acknowledge_view(request):
    if request.method == 'POST':
        FacebookAlbums.instance().acknowledge()
    return redirect('facebook_changes')
