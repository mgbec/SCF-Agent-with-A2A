"""
Authentication gate for the SCF Compliance Agent frontend.

Uses Streamlit's built-in OIDC authentication (st.login / st.user), which works
with any OpenID Connect provider — including the Cognito user pool already
defined in terraform/cognito-a2a.tf.

Configuration lives in .streamlit/secrets.toml (git-ignored). See
.streamlit/secrets.toml.example for the required keys.

Every page must call require_login() as its first Streamlit command after
set_page_config(). Pages render nothing until the user is authenticated.
"""

from __future__ import annotations

import streamlit as st


def _auth_configured() -> bool:
    """True if OIDC auth secrets are present."""
    try:
        return bool(st.secrets.get("auth", {}).get("client_id"))
    except Exception:
        return False


def require_login():
    """
    Block the page until the user is authenticated.

    Renders a login screen and calls st.stop() for anonymous users, so no
    page content is exposed before authentication. Returns the authenticated
    user object (st.user) once logged in.
    """
    if not _auth_configured():
        st.error(
            "🔒 Authentication is not configured. This frontend must not be "
            "exposed without login.\n\n"
            "Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` "
            "and fill in your OIDC provider details (e.g. the Cognito pool from "
            "`terraform/cognito-a2a.tf`), then restart Streamlit."
        )
        st.stop()

    if not getattr(st.user, "is_logged_in", False):
        st.title("🛡️ SCF Compliance Agent")
        st.caption("Secure Controls Framework 2026.2")
        st.markdown("### Sign in required")
        st.write("You must sign in to access the compliance agent and answer approval workflow.")
        st.button("🔐 Log in", type="primary", on_click=st.login)
        st.stop()

    return st.user


def current_user_label() -> str:
    """
    A stable, human-readable identifier for the signed-in user, for audit
    fields (approvals, rejections). Prefers email, falls back to name/sub.
    """
    user = st.user
    return (
        getattr(user, "email", None)
        or getattr(user, "name", None)
        or getattr(user, "sub", None)
        or "unknown"
    )


def render_logout_sidebar():
    """Render a small identity + logout control in the sidebar."""
    with st.sidebar:
        st.divider()
        st.caption(f"Signed in as **{current_user_label()}**")
        st.button("Log out", on_click=st.logout, key="_logout_btn")
