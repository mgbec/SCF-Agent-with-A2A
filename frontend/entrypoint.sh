#!/usr/bin/env bash
# Assemble .streamlit/secrets.toml from environment, then start Streamlit.
#
# App Runner injects:
#   - runtime env vars:     AUTH_CLIENT_ID, AUTH_SERVER_METADATA_URL, AUTH_REDIRECT_URI
#   - runtime secrets:      AUTH_CLIENT_SECRET, AUTH_COOKIE_SECRET  (from SSM SecureString)
# Streamlit's native OIDC (st.login / st.user) reads the [auth] block from this file.
set -euo pipefail

: "${AUTH_CLIENT_ID:?AUTH_CLIENT_ID is required}"
: "${AUTH_CLIENT_SECRET:?AUTH_CLIENT_SECRET is required}"
: "${AUTH_COOKIE_SECRET:?AUTH_COOKIE_SECRET is required}"
: "${AUTH_SERVER_METADATA_URL:?AUTH_SERVER_METADATA_URL is required}"
: "${AUTH_REDIRECT_URI:?AUTH_REDIRECT_URI is required}"

mkdir -p /app/.streamlit
umask 077
cat > /app/.streamlit/secrets.toml <<EOF
[auth]
redirect_uri = "${AUTH_REDIRECT_URI}"
cookie_secret = "${AUTH_COOKIE_SECRET}"
client_id = "${AUTH_CLIENT_ID}"
client_secret = "${AUTH_CLIENT_SECRET}"
server_metadata_url = "${AUTH_SERVER_METADATA_URL}"
EOF

exec streamlit run app.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
