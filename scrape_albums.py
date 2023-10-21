"""
playwright install --with-deps firefox
"""
from argparse import ArgumentParser
import json
from pathlib import Path
import re
import time
from tqdm import tqdm
from playwright.sync_api import sync_playwright

DATA_PATH = Path(__file__).parent / ".scraped_album_data"
ALBUM_ID_REGEX = re.compile(r"https:\/\/www\.facebook\.com\/media\/set\/\?set=a\.(\d+)&type=3")
ALBUM_NAME_REGEX = re.compile(r"(?P<title>.+)\n(?P<count>\d+)\sitems*", flags=re.I)

IDS_TO_IGNORE = [
    "489076346765992",  # Mobile uploads
    "489076353432658",  # Timeline photos
    "590092243331068",  # India 2 -happily homed
    "552824437057849",  # Paddy - Happily homed - staying with foster family
    "557912256549067",  # Aika - happily homed
    "518958043777822",  # Luna - Happily Homed
    "612315007775458",  # Izzi - happily homed
    "557913456548947",  # Dotty -Happily Homed
    "489076360099324",  # Cover photos
    "489076350099325",  # Profile pictures
    "478527842488598",  # All dogs for adoption/foster/ sponsor
    "1892881417719893",  # Gladys -Happily Homed
    "1456923637982342",  # In Loving Memory
    "1022503768091000",  # Sponsor a Hound Programme
    "342935776047806",  # Happily Homed Dogs
    "1147766635564712",  # Vega, Dina & Balto - their journey
    "819257798415599",  # Pal - a remarkable love story -saved from the brink of death
    "795739000767479",  # Nino - in memoriam see Nino's Tale for his story
    "177583412583044",  # Pacita The Pod who Started it All!
]


ALBUMS_NOT_ACCESSIBLE_VIA_API = [
    "1883457118662323",  # Puma
    "1892887014386000",  # Alicia
    "1892885781052790",  # Paloma the third
    "1793339751007394",  # Ginger
    "1859859784355390",  # Murray
    "1642143862793651",  # Santos
    "1814842875523748",  # India
    "1839040019770700",  # Esperanza
    "1810360705971965",  # Lucky
    "1773803669627669",  # Bonnie
]


def dismiss_login(page):
    page.goto("http://facebook.com/podencosinneedscotland/photos_albums")
    page.get_by_role("button", name="Decline optional cookies").click()
    page.get_by_label("Close").click()


def scroll_to_end(page):
    curr_height = page.evaluate('(window.innerHeight + window.scrollY)')
    while True:
        print(f"Scrolling ({curr_height})...")
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(1_000)
        new_height = page.evaluate('(window.innerHeight + window.scrollY)')
        if page.get_by_role("link", name="Videos").is_visible():
            break
        if curr_height == new_height:
            break
        curr_height = new_height


def get_album_link_elements(page):
    print("Loading album links")
    scroll_to_end(page)
    all_links = page.get_by_role("link")    
    album_links = [link for link in all_links.all() if "media" in link.get_attribute("href")]
    return album_links


def get_albums_data(album_links):
    album_data = {
        "total_album_count": len(album_links),
        "albums": {}    
    }
    for album in tqdm(album_links, "Parsing album links"):
        url = album.get_attribute("href")
        album_id = ALBUM_ID_REGEX.findall(url)[0]
        if album_id not in IDS_TO_IGNORE:
            match = ALBUM_NAME_REGEX.match(album.inner_text())
            album_title = match.group("title")
            count = int(match.group("count"))

            album_data["albums"][album_id] = {
                "link": album.get_attribute("href"),
                "name": album_title,
                "count": count,
            }
    album_data["relevant_album_count"] = len(album_data["albums"])
    return album_data


def load_existing_data():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return {}


def fetch_non_api_data(page, new_album_data, existing_album_data=None):
    existing_album_data = existing_album_data or load_existing_data()
    new_albums = new_album_data["albums"]

    print("Fetching data not available by API")
    full_album_data = {}
    for album_id in ALBUMS_NOT_ACCESSIBLE_VIA_API:
        if album_id not in new_albums:
            print(f"\t{album_id} not found in scraped data.")
            continue

        this_album_data = dict(new_albums[album_id])
        page.goto(this_album_data["link"])
        print(f"\tLoading album for {album_id} - {this_album_data['name']}")

        print("\tFinding description")
        see_more_btn = page.get_by_text("See more")
        if see_more_btn.is_visible():
            see_more_btn.click()
        attempts = 0
        while attempts < 3:
            matches = page.locator('css=span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x10flsy6.x6prxxf.xvq8zen.xo1l8bm.xzsf02u').all()
            if matches:
                break
            time.sleep(1)
            attempts += 1

        description = matches[-1].inner_text()
    
        this_album_data["description"] = description.strip(" See less")
        
        last_photo = page.get_by_label("Photo album photo").all()[-1]

        photos = None
        while True:
            print("\tScrolling...")
            last_photo.hover()
            photos = page.get_by_label("Photo album photo")
            # scroll last photo into view if nexessary
            photos.element_handles()[-1].scroll_into_view_if_needed()
            # Scroll and wait for items to load
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1_000)
            photos = page.get_by_label("Photo album photo")
            last_photo = photos.element_handles()[-1]
            items_on_page_after_scroll = len(photos.element_handles())
            # Stop if we've reached the total items, or the max (~50)
            if (items_on_page_after_scroll >= this_album_data["count" ])  or items_on_page_after_scroll > 50:
                print(f"{items_on_page_after_scroll}/{this_album_data['count']} photos loaded")
                break

        for photo in tqdm(photos.all(), "Parsing image links"):
            link = photo.get_by_role("img").get_attribute("src")
            this_album_data.setdefault("images", []).append({"image_url": link})

        full_album_data[album_id] = this_album_data

    new_album_data["non_api_albums"] = full_album_data

    return full_album_data


def diff(all_album_data, all_existing_data=None, report_only=False):
    print("\nCalculating diff")
    if not DATA_PATH.exists():
        DATA_PATH.write_text(json.dumps(all_album_data, indent=2))
        print(f"No existing file, data written to {DATA_PATH}")
        return
    else:
        all_existing_data = all_existing_data or load_existing_data()
    
    print("\nTOTAL ALBUM COUNT")
    print("==========")
    if all_album_data["total_album_count"] != all_existing_data["total_album_count"]:
        print(f'Was: {all_existing_data["total_album_count"]}; Now: {all_album_data["total_album_count"]}')
    else:
        print(f'No change: {all_album_data["total_album_count"]}')
    
    print("\nRELEVANT ALBUM COUNT")
    print("==========")
    if all_album_data["relevant_album_count"] != all_existing_data["relevant_album_count"]:
        print(f'Was: {all_existing_data["relevant_album_count"]}; Now: {all_album_data["relevant_album_count"]}')
    else:
        print(f'No change: {all_album_data["relevant_album_count"]}')


    print("\nDIFF FROM PREVIOUS SCRAPE")
    print("=========================")
    if all_existing_data == all_album_data:
        print("None")
    else:
        # new items
        album_data = all_album_data["albums"]
        existing_data = all_existing_data["albums"]

        new_albums = set(album_data) - set(existing_data)
        if new_albums:
            print("NEW ALBUMS")
            print("==========")
            for album_id in new_albums:
                print(f"{album_id}: {album_data[album_id]['name']}")

        removed_albums = set(existing_data) - set(album_data)
        if removed_albums:
            print("REMOVED ALBUMS")
            print("==============")
            for album_id in removed_albums:
                print(f"{album_id}: {existing_data[album_id]['name']}")

        print("\nCHANGED")
        print("=======")
        changed = False
        for album_id in set(album_data) & set(existing_data):
            if album_data[album_id] != existing_data[album_id]:
                changed = True
                print(
                    f"{album_id}:\n\t"
                    f"Old: {existing_data[album_id]}\n\t"
                    f"New: {album_data[album_id]}"
                )
        if not changed:
            print("No changes to existing albums")
    if not report_only:
        bu_path = DATA_PATH.parent / f"{DATA_PATH}_bu"
        print(f"\nOld file backed up to {bu_path}")
        DATA_PATH.rename(bu_path)
        DATA_PATH.write_text(json.dumps(all_album_data, indent=2))
        print(f"\nNew written to {DATA_PATH}")
    else:
        print("Reporting diff only, no file written")

def main(report_only=False):
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        dismiss_login(page)
        album_links = get_album_link_elements(page)
        old_album_data = load_existing_data()
        new_album_data = get_albums_data(album_links)
        if not report_only:
            fetch_non_api_data(page, new_album_data, old_album_data)
        browser.close()
        diff(new_album_data, old_album_data, report_only)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--report-only", action="store_true", help="Report on diff only")
    args = parser.parse_args()
    main(args.report_only)    
