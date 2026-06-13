"""Central configuration for the Lead Scraper.

Top-level settings (API keys, cookie config, client name) are read from the
environment. The per-user login table is read from the Streamlit secrets file
under an ``[auth.users.*]`` table. This split is deliberate: in deployment the
container materializes ``.streamlit/secrets.toml`` at startup, the app bridges
its top-level keys into the environment (see app.py), and the nested user table
is read straight from ``st.secrets`` here.

Locally, create ``.streamlit/secrets.toml`` (git-ignored) from
``secrets.toml.example`` to supply the same values.
"""

import os

import streamlit as st


def _setting(key, default=None):
    """Read a top-level config value: environment first (which on deployment
    is bridged from secrets.toml by app.py, and locally comes from .env), then
    st.secrets as a fallback, then the default."""
    val = os.getenv(key)
    if val not in (None, ""):
        return val
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        # No secrets file present (typical for bare local runs).
        pass
    return default


# --- Top-level settings ----------------------------------------------------

CLIENT_NAME = _setting("CLIENT_NAME", "Lead Scraper")
COOKIE_NAME = _setting("COOKIE_NAME", "lead_scraper_auth")
# No default: the app must refuse to start without an explicit cookie key
# rather than fall back to a guessable one that would let anyone forge a
# session. auth.py enforces this.
COOKIE_KEY = _setting("COOKIE_KEY")
COOKIE_EXPIRY_DAYS = int(_setting("COOKIE_EXPIRY_DAYS", "30"))


class ConfigError(RuntimeError):
    """Raised when required auth configuration is missing or malformed."""


def load_credentials():
    """Build the streamlit-authenticator credentials dict from the
    ``[auth.users.*]`` table in the Streamlit secrets file.

    Expected secrets.toml shape::

        [auth.users.alice]
        name = "Alice Example"
        password = "$2b$12$...bcrypt hash..."
        email = "alice@example.com"   # optional

    Returns a dict shaped as
    ``{"usernames": {"alice": {"name": ..., "password": ..., "email": ...}}}``.

    Raises ConfigError if the table is missing or empty so the caller can fail
    loudly instead of starting an ungated app.
    """
    try:
        auth_section = st.secrets["auth"]["users"]
    except Exception as exc:
        raise ConfigError(
            "No [auth.users.*] table found in the Streamlit secrets file. "
            "The app cannot start without at least one configured user."
        ) from exc

    usernames = {}
    for username, info in dict(auth_section).items():
        info = dict(info)
        password = info.get("password")
        if not password:
            raise ConfigError(
                f"User '{username}' is missing a 'password' (bcrypt hash) in "
                "the secrets file."
            )
        entry = {
            "name": info.get("name", username),
            "password": password,
        }
        # email is optional; include it only when present so
        # streamlit-authenticator doesn't show a blank.
        if info.get("email"):
            entry["email"] = info["email"]
        usernames[username] = entry

    if not usernames:
        raise ConfigError(
            "The [auth.users.*] table is present but contains no users."
        )

    return {"usernames": usernames}
