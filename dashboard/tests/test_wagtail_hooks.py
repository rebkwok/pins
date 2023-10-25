import json

from bs4 import BeautifulSoup
import pytest

pytestmark = pytest.mark.django_db


def test_collections_admin_menu_item(client, admin_user, home_page):
    client.force_login(admin_user)
    resp = client.get(f"/admin/pages/{home_page.id}/edit", follow=True)
    soup = BeautifulSoup(resp.rendered_content, "html.parser")
    props = soup.find("script", id="wagtail-sidebar-props")
    content = json.loads(props.contents[0])
    main_menu_module = [
        module for module in content["modules"] 
        if module["_type"] == "wagtail.sidebar.MainMenuModule"
    ]
    # the first one is the main side bar (following by account section and admin link)
    side_bar_items = main_menu_module[0]["_args"][0]
    
    # get all the labels, ignoring submenus
    top_level_side_bar_labels = {
        arg_["label"] for item in side_bar_items
        for arg_ in item["_args"]
        if isinstance(arg_, dict)
    }
    assert "Collections" in top_level_side_bar_labels
