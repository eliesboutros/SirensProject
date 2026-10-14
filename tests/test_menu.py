"""Every page carries the same grouped menu, with its own page marked current."""
import re

import pytest

PAGES = [("/", "New report"), ("/brief", "Pre-arrival brief"), ("/dashboard", "Dashboard"),
         ("/review", "Review links"), ("/tree", "Link tree"), ("/map", "Map"),
         ("/demo", "Load demo data"), ("/vendor-check", "Offline check")]


@pytest.mark.parametrize("path,label", PAGES)
def test_page_has_the_shared_menu(client, path, label):
    client.post("/seed")                      # the tree page needs incidents to render
    html = client.get(path).data.decode()
    assert html.count('<nav class="sm"') == 1
    groups = re.findall(r'class="sm-head[^"]*"[^>]*>([^<]+)<', html)
    assert groups == ["Reports", "Analysis", "Data"]
    hrefs = re.findall(r'<a class="sm-item[^"]*"(?: aria-current="page")? href="([^"]+)"', html)
    assert hrefs == ["/", "/brief", "/dashboard", "/review", "/tree", "/map", "/demo", "/vendor-check"]
    current = re.findall(r'aria-current="page" href="[^"]+"><strong>([^<]+)</strong>', html)
    assert current == [label]


def test_menu_pins_its_header_and_offsets_anchors(client):
    html = client.get("/demo").data.decode()
    assert "host.style.position = 'sticky'" in html
    assert "scrollPaddingTop" in html
