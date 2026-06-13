"""Login gate for the Lead Scraper.

Wraps the whole app: ``require_login()`` renders the login form and stops the
script for anyone who isn't authenticated, so unauthenticated visitors never
reach the Search / My Leads UI. This is the mechanism that keeps each hosted
client instance private — a client gets only a URL and a login, never the code.
"""

import streamlit as st
import streamlit_authenticator as stauth

from config import (
    CLIENT_NAME,
    COOKIE_EXPIRY_DAYS,
    COOKIE_KEY,
    COOKIE_NAME,
    ConfigError,
    load_credentials,
)


def _build_authenticator():
    """Construct the Authenticate object, failing loudly if required config
    is missing. Returns None after rendering an error + stopping the app."""
    if not COOKIE_KEY:
        st.error(
            "Server misconfigured: COOKIE_KEY is not set. The app will not "
            "start without one. (Set COOKIE_KEY in the deployment secrets or "
            "your local .streamlit/secrets.toml.)"
        )
        st.stop()

    try:
        credentials = load_credentials()
    except ConfigError as exc:
        st.error(f"Server misconfigured: {exc}")
        st.stop()

    # auto_hash=False: passwords in the secrets file are already bcrypt hashes
    # (produced by gen_password_hash.py); we must not re-hash them on load.
    return stauth.Authenticate(
        credentials,
        COOKIE_NAME,
        COOKIE_KEY,
        COOKIE_EXPIRY_DAYS,
        auto_hash=False,
    )


def require_login():
    """Render the login form and gate the app.

    On a valid, authenticated session this returns the authenticator (so the
    caller can render a logout control). Otherwise it renders the appropriate
    message and halts the script via ``st.stop()`` — nothing below the call
    site executes for an unauthenticated visitor.
    """
    authenticator = _build_authenticator()

    authenticator.login(location="main")

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("Invalid username or password.")
        st.stop()
    if status is None:
        st.info(f"Please log in to access {CLIENT_NAME}.")
        st.stop()

    return authenticator


def render_logout(authenticator):
    """Show who's logged in plus a logout button in the sidebar."""
    name = st.session_state.get("name") or st.session_state.get("username", "")
    with st.sidebar:
        if name:
            st.caption(f"Signed in as **{name}**")
        authenticator.logout("Log out", location="sidebar")
