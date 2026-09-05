# DB Setup

Ensure postgres is installed and running.

Create DB (with username/password/dbname to match DATABASE_URL env var):

```
psql postgres

CREATE ROLE pins WITH LOGIN CREATEDB PASSWORD 'xxxxx';
CREATE DATABASE pins OWNER pins;

```

# Site setup

Create a superuser.

Run the server, login, go to /admin

Create a new homepage.

Go to Pages, add child page to Root, with type Homepage.

Delete the default root Page.

Associate the new homepage with a site. Go to Sites and Add a site.
For a dev server, hostname can be anything. Add the homepage you just created as the Root page, and
check Is default site.

Go to the root URL and the Homepage should now be rendered.

Create any new pages as child pages of the homepage.