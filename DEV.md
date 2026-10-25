# PINS website: development and deployment notes

# Local development

## Requirements

- Python 3.13 (see `.python-version`) and [uv](https://docs.astral.sh/uv/)
- PostgreSQL (the tests can also run on SQLite: see Tests)
- Optional: [mailcatcher](https://mailcatcher.me/) to see emails in a browser;
  the [Stripe CLI](https://docs.stripe.com/stripe-cli) to test payments

Install the dependencies (including the dev group) with `uv sync`.

## The .env file

Copy `pins/env_sample` to `pins/.env` and fill it in (see Environment
variables). `.env` and `env_sample` are for local development only:
production's environment variables are set with envdir. For local development set at least:

```
SECRET_KEY=<anything>
DEBUG=True
LOCAL=True
DATABASE_URL=postgres://pins:<password>@localhost/pins
```

`LOCAL=True` allows any host, uses the local memory cache, stores media files
in `media/` (unless `LOCAL_S3=True`), prints emails to the console, and doesn't
write a log file (so `LOG_FOLDER` isn't needed).
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` must be present when `LOCAL` is
on (they can be blank unless `LOCAL_S3` is on). The Facebook, PayPal, Stripe and
encryption settings must be present too (dummy values are fine if you're not
using those parts of the site).

## Database

Ensure postgres is installed and running. Create the database (with the
username/password/dbname in DATABASE_URL):

```
psql postgres

CREATE ROLE pins WITH LOGIN CREATEDB PASSWORD 'xxxxx';
CREATE DATABASE pins OWNER pins;
```

Then `uv run python manage.py migrate`. (The migrations create the shop's user
groups and the Shop image collection.)

## Site setup

Create a superuser (`uv run python manage.py createsuperuser`), run the server,
log in, and go to /admin.

Create a new homepage: go to Pages, add a child page to Root, with type
Homepage. Delete the default root Page.

Associate the new homepage with a site: go to Settings > Sites and add a site.
For a dev server, the hostname can be anything. Add the homepage you just
created as the Root page, and check "Is default site".

Go to the root URL and the Homepage should now be rendered. Create any new
pages as child pages of the homepage.

## Running the server

```
uv run python manage.py runserver 0.0.0.0:7700
```

(The Stripe notes below assume port 7700.)

Emails are printed to the console with `LOCAL=True`. To see them in a browser
instead, run mailcatcher and set `USE_MAILCATCHER=True` with `LOCAL` off (on
port 1025; the web interface is at http://127.0.0.1:1080).

Set `LOG_LEVEL=DEBUG` to see the site's debug logs (e.g. the shop's stock
checks).

# The shop locally

## Example products: seed_shop

```
uv run python manage.py seed_shop [--sale]
```

Creates a shop page (at /shop/, under the default site's root page), three
categories, and products with generated placeholder images (in a "Shop seed
images" collection) covering the cases the shop handles: products with options
(a calendar, a T-shirt and a hoodie, in sizes and colours), several images,
an out-of-stock product, products with no image, and a raffle ticket that
doesn't need shipping. With `--sale`, also a current sale on the mug. Anything that already exists is
skipped, so it can be run again. It only runs with `DEBUG` on (`--force` to
run anyway). The site must be set up first (a default site with a root page).

## Importing the current shop's products: import_shop_stock

```
uv run python manage.py import_shop_stock pins_current_stock.csv --dry-run
uv run python manage.py import_shop_stock pins_current_stock.csv [--reset-stock]
```

Imports products from the old shop's stock CSV (the columns and options are
described in `shop/management/commands/import_shop_stock.py`). The dispatchers'
users must exist (`--create-dispatchers` creates them, for testing). Existing
products are skipped, or with `--reset-stock`, have their stock set back to the
CSV's. `--dry-run` reports without saving.

## Expired baskets

Basket items are held for `BASKET_TIMEOUT_MINUTES`. Expired baskets are cleared
(their items returned to stock) as the site is used (at most once a minute),
and by `uv run python manage.py clear_expired_baskets`, which also deletes old
empty baskets. Run it on a cron in production (see Deploying).

## Users and roles

The migrations create the shop's groups:
- **Shop admins**: the shop's stock, setup (sales, discount codes, settings,
  activity) and orders, and images in the Shop collection.
- **Shop manager**: orders and Dispatcher activity only (they start at the
  orders list).
- **Dispatchers**: their own items to send (they start there). Add users as
  dispatchers on the Dispatcher activity page (needs permission to change
  users, e.g. a superuser), then choose them as products' dispatchers (they're
  emailed about new orders for those products if they have an email address).

Superusers can see the admin as any of these groups: Settings > View as a role.
Connecting the Stripe account needs the "Can connect or disconnect the Stripe
account" permission (superusers have it).

## Shop settings (set these in the admin: Shop admin > Shop settings)

- The email addresses to email new orders to
- The reply-to address for shop emails
- The shipping cost (a flat rate for every delivered order)

## The old order forms (deprecated)

The order form pages (`OrderFormPage` in `home/models.py`), their order
views at /orders/ (`home/orders_urls.py`) and their PayPal payments are
deprecated in favour of the shop app and Stripe, but are kept for now. (PayPal
is also used by the fundraising app, e.g. recipe book submissions.)

# Environment variables

Locally in `pins/.env` (see `pins/env_sample`); in production, with envdir.
Required unless a default is given.

**Core**
- `SECRET_KEY`
- `DEBUG`: True/False (default False)
- `LOCAL`: True for local development (default False; see The .env file)
- `DATABASE_URL`: e.g. `postgres://user:password@localhost/pins`
- `ALLOWED_HOSTS`: comma-separated (default `podencosinneed.org,www.podencosinneed.org`;
  any host when `LOCAL`)
- `LOG_FOLDER`: the folder `pins.log` is written to (not needed with `LOCAL`)
- `LOG_LEVEL`: the site's own apps' log level (default INFO; e.g. DEBUG)

**Email** (production: Amazon SES)
- `AWS_SES_ACCESS_KEY_ID`, `AWS_SES_SECRET_ACCESS_KEY`, `AWS_SES_REGION_NAME`,
  `AWS_SES_REGION_ENDPOINT`: only needed when none of `LOCAL`, `CI` or
  `USE_MAILCATCHER` is set (i.e. production), so they're not in `env_sample`
- `USE_MAILCATCHER`: send emails to mailcatcher (default False; with `LOCAL` off)

**Media storage** (production: S3, with the server's IAM role)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: local only (with `LOCAL` or
  `LOCAL_S3`)
- `LOCAL_S3`: use S3 for media locally (default False)
- `AWS_S3_CUSTOM_DOMAIN`: if using CloudFront (default blank)
- `AWS_S3_URL_PROTOCOL`: default `http:`

**The shop**
- `SALESMAN_STRIPE_CONNECT_SECRET_KEY`: the platform's Stripe secret key
  (`sk_test_...` or `sk_live_...`)
- `SALESMAN_STRIPE_CONNECT_CLIENT_ID`: the platform's Connect client id (`ca_...`)
- `SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET`: the webhook endpoint's signing
  secret (`whsec_...`; see Stripe webhooks)
- `SALESMAN_STRIPE_CONNECT_PAGES_ENABLED`: the pages for connecting the PINS
  account (/stripe/connect/; default True; False once it's connected)
- `BASKET_TIMEOUT_MINUTES`: how long baskets' items are held (default 30, the
  minimum, to match Stripe Checkout's minimum session length; under 24 hours)
- `HIDE_SEARCH`, `HIDE_BREADCRUMBS`: hide the header's search box and the
  breadcrumbs (default False)

**Other parts of the site**
- Facebook (dog albums): `FB_APP_ID`, `FB_APP_SECRET`, `FB_ACCESS_TOKEN` (a
  short-lived page token to start with; it's exchanged for a long-lived one),
  `FB_PAGE_ID`, `FB_EXTRA_ALBUM_IDS_TO_IGNORE` (optional, comma-separated)
- PayPal (the old order forms, and fundraising): `PAYPAL_EMAIL`, `PAYPAL_CUSTOM_KEY`, `PAYPAL_TEST`
  (default False), `PAYPAL_TEST_CALLBACK_DOMAIN` (optional)
- reCAPTCHA (forms): `RECAPTCHA_PUBLIC_KEY`, `RECAPTCHA_PRIVATE_KEY` (default
  blank)
- Encryption (form submissions): `FIELD_ENCRYPTION_KEY`, `PDF_ENCRYPTION_KEY`
- `RECIPE_SUBMISSIONS_OPEN`: default False

# Stripe

The shop takes payments with Stripe Checkout, through Stripe Connect: the PINS
Stripe account is connected to the platform (PINS's website) account, and
payments are direct charges on it. No publishable key is needed (Checkout is
hosted by Stripe).

The Stripe integration is the
[django-salesman-stripe-connect](https://github.com/rebkwok/django-salesman-stripe-connect)
package (installed from GitHub at a fixed commit, see `pyproject.toml`), with
the shop's customisations in `shop/payment.py`. To change it, change the
package, push it, and update the commit in `pyproject.toml`.

## Webhooks

Payments are direct charges on the connected (PINS) account, so the checkout
sessions, payments and refunds belong to the connected account, and the webhook
must receive events from connected accounts.

Create the endpoint in the platform account's dashboard (in sandbox/test mode for
testing), not in the PINS account:
- Add a new webhook endpoint that listens to events on **Connected accounts**
  (not "Your account").
- URL: `https://<domain>/stripe/webhook/`
- API version: `2026-09-30.endive` (the version the code uses)
- Listen for:
  - checkout.session.completed
  - checkout.session.expired
  - charge.refunded (full or partial refunds, from the orders admin or the PINS
    Stripe dashboard)
  - charge.refund.updated (a refund failed or was cancelled)
  - charge.dispute.created (a customer has disputed a payment (chargeback);
    the order is flagged and the shop notified, as PINS needs to respond in
    their Stripe dashboard)
  - charge.dispute.closed (the dispute was won or lost; noted on the order)
  - account.application.authorized (an account connected to the platform;
    logged)
  - account.application.deauthorized (PINS disconnected their account from the
    platform: the saved account is removed and the shop emailed; payments can't
    be taken until an account is connected again at /stripe/connect/)
  - (If BACS is added: not for now, as it would mean handling payments that
    are pending for several days and could be reversed)
    - checkout.session.async_payment_succeeded
    - checkout.session.async_payment_failed
- The endpoint has its own signing secret (whsec_...); set it as
  SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET in that environment (production's
  envdir).

Each event includes `account: "acct_..."`; events from any account other than the
PINS connected account are ignored (apart from the authorized/deauthorized events).

The PINS account needs the `card_payments` capability to take direct charges (should be set already).

## Connecting an account

The user connecting the PINS Stripe account must be an existing user with the "Can connect or disconnect
the Stripe account" permission. The should go to https://podencosinneed.org/stripe/connect/ and
click the button to connect the account.

Once the account is connected (in production), set SALESMAN_STRIPE_CONNECT_PAGES_ENABLED=False
to disable the connect pages. To connect a different account, enable the pages again and
disconnect the current one at /stripe/connect/disconnect/ (or disconnect it in Stripe,
which removes it here via the webhook).

## Testing payments locally

In the stripe dashboard, ensure you're using sandbox mode.

Find SALESMAN_STRIPE_CONNECT_SECRET_KEY (sk_test_...), and SALESMAN_STRIPE_CONNECT_CLIENT_ID
(ca_..., in Connect settings) and add them to `pins/.env`.

Enable Oauth for Connect:
https://dashboard.stripe.com/test/settings/connect/onboarding-options/oauth
(https://dashboard.stripe.com/settings/connect/onboarding-options/oauth for non-sandbox)
Add callback URIs (assuming running local server on port 7700):
http://localhost:7700/stripe/oauth/callback/ 
http://127.0.0.1:7700/stripe/oauth/callback/ 

Connect an account: log in as a superuser (or a user with the "Can connect or disconnect
the Stripe account" permission) and go to http://localhost:7700/stripe/connect/.
On Stripe's page, log in to a test account to connect it, or click "skip this
form" to connect to a new dummy test connected account. Only one account can be
connected; the connected account is saved in the database (ConnectedAccount).

Use the stripe CLI to test webhooks:
```
stripe login
stripe accounts retrieve (to set your account API keys)
stripe config --list (to check)
# --forward-connect-to forwards events from connected accounts (not --forward-to,
# which only forwards the platform account's events)
stripe listen --forward-connect-to localhost:7700/stripe/webhook/ --events checkout.session.completed,checkout.session.expired,charge.refunded,charge.refund.updated,charge.dispute.created,charge.dispute.closed,account.application.authorized,account.application.deauthorized --log-level=debug
```

It will print a webhook signing secret (one secret covers both platform and connected
account events) - add it to your .env's SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET and restart the dev server. 

(Note: if you see the checkout.session.completed firing but it's not calling the webhook endpoint, the
alternative is to set up a tunnel with zrok.io and add a real webhook in the stripe test environment
that listens for the checkout.session.completed event.)


# Tests

```
uv run pytest            # the unit tests, in parallel
uv run pytest --cov      # with coverage
uv run coverage report --include="shop/*" --fail-under=100
```

They need a database: DATABASE_URL (PostgreSQL as in CI, or e.g.
`sqlite:////tmp/pins-test.sqlite3` for speed). The test settings are in
`pyproject.toml` (`[tool.pytest]`). The shop must have 100% coverage (checked
in CI).

## Browser (end-to-end) tests

The shop's main journeys are tested in a real browser with Playwright
(`shop/tests/e2e`). They're marked `e2e` and left out of the normal test run;
run them with:

```
uv run playwright install --with-deps chromium   # once
uv run pytest -m e2e -n 2
```

Add `--headed --slowmo 500` to watch them, or `--tracing retain-on-failure`
to keep a trace of failures (open with `uv run playwright show-trace
test-results/.../trace.zip`). Stripe isn't called (its API is faked), but
the pages load htmx and Bootstrap from CDNs, so they need internet access.
They also run axe-core on the main shop and admin pages, failing on serious
or critical accessibility issues. CI runs them as a separate job.

# Deploying

Every deploy:
- `python manage.py migrate`
- `python manage.py collectstatic --noinput` (static files are served by
  WhiteNoise)
- Restart the app server

## Cron jobs

- `python manage.py clear_expired_baskets`: every 5 minutes or so (returns
  expired baskets' items to stock; deletes old empty baskets)

## The shop's first deploy and launch

**Before the first deploy**
- Set the shop's environment variables, with Stripe's **test** keys to begin
  with: `SALESMAN_STRIPE_CONNECT_SECRET_KEY` (`sk_test_...`),
  `SALESMAN_STRIPE_CONNECT_CLIENT_ID` (the test `ca_...`),
  `SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET` (from the test webhook endpoint),
  `SALESMAN_STRIPE_CONNECT_PAGES_ENABLED=True`.
- In the platform's Stripe dashboard (test mode): enable OAuth for Connect,
  with the redirect URI `https://podencosinneed.org/stripe/oauth/callback/`,
  and create the webhook endpoint for events on connected accounts (see
  Webhooks).
- Set up the `clear_expired_baskets` cron.

**After deploying (a hidden preview)**
- Import the products: `import_shop_stock` with `--dry-run` first, then
  without. The dispatchers' users must exist first, with email addresses.
  Then add the products' images in the admin.
- Add the shop page under the home page with a hard-to-guess slug, "Show in
  menus" off, and publish it.
- Create users and give them roles (see Users and roles); fill in the shop
  settings.
- Connect PINS's **test** Stripe account at /stripe/connect/.
- Test: orders with Stripe's test cards (4242 4242 4242 4242, any future date
  and CVC), collection and delivery, discount codes, shipping, refunds, the
  emails, and the dispatcher view; check the webhook events reach the site
  (Stripe dashboard > Webhooks).

**Launch**
1. In the platform's **live** Stripe dashboard, enable OAuth for Connect (same
   redirect URI) and create the live webhook endpoint (same events). Set the
   live secret key, client id and webhook secret, and restart.
2. Disconnect the test account at /stripe/connect/disconnect/, connect PINS's
   live account at /stripe/connect/, then set
   `SALESMAN_STRIPE_CONNECT_PAGES_ENABLED=False` and restart.
3. Clear out the test orders, baskets and used test discount codes, and reset
   the stock: `import_shop_stock` with an up-to-date CSV and `--reset-stock`.
4. Change the old Shop page's slug (e.g. `shop-old`), and delete the /shop/
   redirect Wagtail makes for it. Give the new shop page the slug `shop`, turn
   on "Show in menus", and publish. Then unpublish the old Shop page.
5. Check the menus, /shop/, a product, the basket, and a small real payment
   (refunded from the order page), and watch the first orders' webhook events
   and emails.
