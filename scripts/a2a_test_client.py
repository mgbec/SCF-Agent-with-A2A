"""
A2A Test Client - exercises the deployed A2A ingress as a real second agent would.

Two auth modes against the Cognito-guarded route (`/cognito/rpc`):
    login   Interactive Cognito hosted-UI login (authorization_code + PKCE, no
            client secret). Opens your browser; a local loopback server catches
            the redirect automatically. This is "the Cognito login" path.
    m2m     Machine-to-machine client_credentials (no browser, no user).

Either way this is a genuine A2A client: it fetches the Agent Card, then talks
JSON-RPC 2.0 over the real deployed API Gateway route.

Usage:
    python a2a_test_client.py --auth login "Look up SCF control GOV-01"
    python a2a_test_client.py --auth m2m "What controls map to HIPAA?"
    python a2a_test_client.py --auth login --interactive
    python a2a_test_client.py --card-only

Requires the Cognito user pool to have at least one confirmed user for --auth
login (see docs/user-guide.md - admin-create-user or admin-set-user-password).

Reads endpoints and client IDs from `terraform output`, so run this from a
checkout with the deployed Terraform state available (or export the
TF_OUTPUT_OVERRIDES noted below for CI / a different machine).
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

# The agent's replies can contain em-dashes etc.; force UTF-8 so they print on
# a Windows cp1252 console instead of raising UnicodeEncodeError or mangling.
# line_buffering=True matters here: stdout is fully buffered when it's not a
# TTY (piped/redirected/captured), which would otherwise hide the printed
# authorize URL and "waiting for redirect" message behind the blocking wait
# for the OAuth callback.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        pass

TF_DIR = os.path.join(os.path.dirname(__file__), "..", "terraform")

# Optional overrides so this can run without a local Terraform state
# (e.g. CI, or a teammate's machine): set any of these env vars to skip the
# corresponding `terraform output` lookup.
_ENV_OVERRIDES = {
    "a2a_api_endpoint": "A2A_API_ENDPOINT",
    "cognito_a2a_token_endpoint": "COGNITO_A2A_TOKEN_ENDPOINT",
    "cognito_a2a_scope": "COGNITO_A2A_SCOPE",
    "cognito_a2a_web_client_id": "COGNITO_A2A_WEB_CLIENT_ID",
    "cognito_a2a_m2m_client_id": "COGNITO_A2A_M2M_CLIENT_ID",
    "cognito_a2a_m2m_client_secret": "COGNITO_A2A_M2M_CLIENT_SECRET",
}


def tf_output(key: str) -> str:
    env_var = _ENV_OVERRIDES.get(key)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    result = subprocess.run(
        ["terraform", "output", "-raw", key],
        cwd=TF_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"`terraform output {key}` failed: {result.stderr.strip() or '(empty)'}\n"
            f"Run this from a checkout with the A2A stack applied, or set ${_ENV_OVERRIDES.get(key, key.upper())}."
        )
    return result.stdout.strip()


# --------------------------------------------------------------------------- #
# Minimal HTTP JSON client (stdlib only)
# --------------------------------------------------------------------------- #
def http_json(method: str, url: str, headers: dict | None = None, data: dict | None = None, form: bool = False):
    headers = dict(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, _parse_body(resp.read(), resp.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        return exc.code, _parse_body(exc.read(), exc.headers.get("Content-Type", ""))


def _parse_body(raw: bytes, content_type: str):
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


# --------------------------------------------------------------------------- #
# Auth: Cognito hosted-UI login (authorization_code + PKCE)
# --------------------------------------------------------------------------- #
def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if params:
            _CallbackHandler.result = params
        ok = "error" not in params
        body = (
            b"<html><body><h3>Signed in.</h3>You can close this tab and return to the terminal.</body></html>"
            if ok
            else f"<html><body><h3>Login failed</h3><pre>{params}</pre></body></html>".encode()
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep stdout clean; we print our own progress


def cognito_login(domain_base: str, client_id: str, scope: str, redirect_uri: str, timeout: int = 120) -> str:
    """Authorization_code + PKCE against the Cognito hosted UI. Returns an access token."""
    parsed = urllib.parse.urlparse(redirect_uri)
    host, port = parsed.hostname, parsed.port or 80

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    authorize_url = domain_base + "/oauth2/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": scope,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    _CallbackHandler.result = {}
    try:
        server = HTTPServer((host, port), _CallbackHandler)
    except OSError as exc:
        raise RuntimeError(
            f"Couldn't bind {host}:{port} for the OAuth redirect ({exc}). "
            "Something else is listening there - e.g. a local `streamlit run app.py`. "
            "Stop it, or pass a different --redirect-uri that's also in cognito_a2a_web_callback_urls."
        ) from exc
    server.timeout = 5

    print(f"Opening your browser to sign in via Cognito:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)
    print(f"Waiting for the redirect on {redirect_uri} ({timeout}s timeout)...")

    deadline = time.time() + timeout
    params = {}
    while time.time() < deadline:
        server.handle_request()
        params = _CallbackHandler.result
        if params:
            break
    server.server_close()

    if not params:
        raise RuntimeError("Timed out waiting for the Cognito redirect - did you finish signing in?")
    if params.get("state") != state:
        raise RuntimeError("OAuth 'state' mismatch on the redirect - possible CSRF, aborting.")
    if "error" in params:
        raise RuntimeError(f"Cognito returned an error: {params}")

    status, token_resp = http_json(
        "POST",
        domain_base + "/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": params["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        form=True,
    )
    if status != 200:
        raise RuntimeError(f"Token exchange failed ({status}): {token_resp}")
    print(f"Signed in. Granted scope: {token_resp.get('scope', '(none)')}\n")
    return token_resp["access_token"]


def cognito_m2m(token_endpoint: str, client_id: str, client_secret: str, scope: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    status, token_resp = http_json(
        "POST",
        token_endpoint,
        headers={"Authorization": f"Basic {basic}"},
        data={"grant_type": "client_credentials", "scope": scope},
        form=True,
    )
    if status != 200:
        raise RuntimeError(f"client_credentials failed ({status}): {token_resp}")
    return token_resp["access_token"]


# --------------------------------------------------------------------------- #
# A2A client
# --------------------------------------------------------------------------- #
def fetch_agent_card(base_url: str, prefix: str = "cognito") -> dict:
    status, card = http_json("GET", f"{base_url}/{prefix}/.well-known/agent-card.json")
    if status != 200:
        raise RuntimeError(f"Agent card fetch failed ({status}): {card}")
    return card


def _rpc(rpc_url: str, token: str, method: str, params: dict, req_id: str):
    return http_json(
        "POST",
        rpc_url,
        headers={"Authorization": f"Bearer {token}"},
        data={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
    )


def send_message(rpc_url: str, token: str, text: str, context_id: str | None) -> dict:
    message = {"role": "user", "messageId": secrets.token_hex(8), "parts": [{"kind": "text", "text": text}]}
    if context_id:
        message["contextId"] = context_id
    status, body = _rpc(rpc_url, token, "message/send", {"message": message}, req_id="1")
    if status != 200 or "error" in body:
        raise RuntimeError(f"message/send failed ({status}): {body}")
    return body["result"]


def get_task(rpc_url: str, token: str, task_id: str) -> dict:
    status, body = _rpc(rpc_url, token, "tasks/get", {"id": task_id}, req_id="2")
    if status != 200 or "error" in body:
        raise RuntimeError(f"tasks/get failed ({status}): {body}")
    return body["result"]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt", nargs="?", help="Question to send. Omit with --card-only or --interactive.")
    parser.add_argument(
        "--auth",
        choices=["login", "m2m"],
        default="login",
        help="login = Cognito hosted-UI (browser, human user). m2m = client_credentials. Default: login",
    )
    parser.add_argument(
        "--redirect-uri",
        default="http://localhost:8501/oauth2callback",
        help="Must be one of cognito_a2a_web_callback_urls. Default: http://localhost:8501/oauth2callback",
    )
    parser.add_argument("--card-only", action="store_true", help="Fetch and print the Agent Card, then exit.")
    parser.add_argument("--interactive", action="store_true", help="Chat loop instead of a single prompt.")
    parser.add_argument("--context-id", help="Reuse a contextId from a previous run to continue that session.")
    args = parser.parse_args()

    base_url = tf_output("a2a_api_endpoint")
    rpc_url = f"{base_url}/cognito/rpc"

    print(f"=== Agent Card: {base_url}/cognito/.well-known/agent-card.json ===")
    card = fetch_agent_card(base_url)
    print(json.dumps({k: card[k] for k in ("name", "version", "capabilities") if k in card}, indent=2))
    print(f"Security schemes: {list(card.get('securitySchemes', {}))}\n")
    if args.card_only:
        return

    if args.auth == "login":
        token_endpoint = tf_output("cognito_a2a_token_endpoint")
        domain_base = token_endpoint.rsplit("/oauth2/token", 1)[0]
        client_id = tf_output("cognito_a2a_web_client_id")
        scope = "openid email " + tf_output("cognito_a2a_scope")
        token = cognito_login(domain_base, client_id, scope, args.redirect_uri)
    else:
        token = cognito_m2m(
            tf_output("cognito_a2a_token_endpoint"),
            tf_output("cognito_a2a_m2m_client_id"),
            tf_output("cognito_a2a_m2m_client_secret"),
            tf_output("cognito_a2a_scope"),
        )

    context_id = args.context_id

    def ask(prompt: str):
        nonlocal context_id
        print(f">>> {prompt}")
        task = send_message(rpc_url, token, prompt, context_id)
        context_id = task["contextId"]
        answer = task["artifacts"][0]["parts"][0]["text"]
        print(f"<<< {answer}")
        print(f"    task_id={task['id']}  contextId={context_id}  state={task['status']['state']}\n")

    if args.interactive:
        print("Interactive A2A session ('quit' to exit).\n")
        while True:
            try:
                prompt = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if prompt.lower() in ("quit", "exit"):
                break
            if prompt:
                ask(prompt)
    elif args.prompt:
        ask(args.prompt)
    else:
        parser.error("provide a prompt, or use --interactive / --card-only")


if __name__ == "__main__":
    main()
