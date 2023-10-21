#!/bin/bash
set -euo pipefail

cd /opt/sites/pins
. venv/bin/activate

python scrape_albums.py
envdir envdir ./manage.py import_scraped_data -p pins/.scraped_album_data
