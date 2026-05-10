from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.menu import MenuItem

from dogs.models import DogPage, DogStatusPage, FacebookAlbums


@hooks.register('register_admin_menu_item')
def register_facebook_changes_menu_item():
    albums_obj = FacebookAlbums.instance()
    changes = albums_obj.pending_changes()
    has_changes = any(changes.values())
    classname = "facebook-changes-pending" if has_changes else ""
    return MenuItem('Facebook Changes', reverse('facebook_changes'), icon_name='image', classname=classname, order=250)


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


def facebook_changes_view(request):
    albums_obj = FacebookAlbums.instance()
    changes = albums_obj.pending_changes()
    has_changes = any(changes.values())
    return render(request, 'dogs/facebook_changes.html', {
        'changes': _enrich_changes(changes),
        'has_changes': has_changes,
    })


def facebook_acknowledge_view(request):
    if request.method == 'POST':
        FacebookAlbums.instance().acknowledge()
    return redirect('facebook_changes')
