#!/bin/bash
set -euo pipefail

cd /opt/sites/pins
. venv/bin/activate

envdir envdir ./manage.py import_scraped_data -p pins/.scraped_album_data
