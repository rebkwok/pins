import os
import subprocess
import sys

import pytest

# conftest's autouse root_page fixture needs the database
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "timeout,valid", [("29", False), ("30", True), ("1439", True), ("1440", False)]
)
def test_basket_timeout_minutes_setting(timeout, valid):
    # Settings are only loaded once per process, so load them in a new one
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import django; from django.conf import settings; "
            "print(settings.BASKET_TIMEOUT_MINUTES)",
        ],
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "pins.settings",
            "BASKET_TIMEOUT_MINUTES": timeout,
        },
        capture_output=True,
        text=True,
    )
    if valid:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == timeout
    else:
        assert result.returncode != 0
        assert "BASKET_TIMEOUT_MINUTES must be at least 30" in result.stderr
