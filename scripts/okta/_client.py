"""Shared Okta Management API client used by every script in scripts/okta/.

Handles the Private Key JWT client-credentials exchange against the API Services
app defined by OKTA_CLIENT_ID / OKTA_PRIVATE_KEY / OKTA_KEY_ID in the project .env,
then yields a `requests.Session` with Bearer-token auth applied.

The token is fetched once per process and cached in memory. No on-disk caching
here — the MCP server handles keychain caching for its own subprocess; scripts
are short-lived and get a fresh token per run.
"""

import os
import sys
import time
import uuid
from pathlib import Path

import jwt
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent.parent / ".env")

OKTA_ORG_URL = os.getenv("OKTA_ORG_URL", "").rstrip("/")
OKTA_CLIENT_ID = os.getenv("OKTA_CLIENT_ID", "")
OKTA_PRIVATE_KEY = os.getenv("OKTA_PRIVATE_KEY", "")
OKTA_KEY_ID = os.getenv("OKTA_KEY_ID", "")
OKTA_SCOPES = os.getenv("OKTA_SCOPES", "").strip('"').strip()


def _require(name: str, value: str) -> str:
    if not value:
        print(f"ERROR: {name} missing from .env")
        sys.exit(1)
    return value


def _private_key_pem() -> bytes:
    pem = OKTA_PRIVATE_KEY.strip().strip('"')
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    return pem.encode()


def get_access_token() -> tuple[str, str]:
    """Exchange a Private Key JWT assertion for an Okta API access token.

    Returns (access_token, scope_string). The scope string is what Okta actually
    granted, which may be narrower than what we requested.
    """
    _require("OKTA_ORG_URL", OKTA_ORG_URL)
    _require("OKTA_CLIENT_ID", OKTA_CLIENT_ID)
    _require("OKTA_PRIVATE_KEY", OKTA_PRIVATE_KEY)
    _require("OKTA_KEY_ID", OKTA_KEY_ID)
    _require("OKTA_SCOPES", OKTA_SCOPES)

    token_url = f"{OKTA_ORG_URL}/oauth2/v1/token"
    now = int(time.time())
    assertion = jwt.encode(
        payload={
            "iss": OKTA_CLIENT_ID,
            "sub": OKTA_CLIENT_ID,
            "aud": token_url,
            "iat": now,
            "exp": now + 300,
            "jti": uuid.uuid4().hex,
        },
        key=_private_key_pem(),
        algorithm="RS256",
        headers={"alg": "RS256", "kid": OKTA_KEY_ID},
    )
    resp = requests.post(
        token_url,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "scope": OKTA_SCOPES,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: token exchange failed: HTTP {resp.status_code}")
        print(f"  {resp.text}")
        sys.exit(1)
    body = resp.json()
    return body["access_token"], body.get("scope", "")


def get_session() -> tuple[requests.Session, str]:
    """Build an authenticated requests.Session. Returns (session, granted_scopes)."""
    token, granted = get_access_token()
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return session, granted


def api_url(path: str) -> str:
    return f"{OKTA_ORG_URL}{path}"


def paginate(session: requests.Session, url: str, params: dict | None = None):
    """Yield items from a paginated Okta list endpoint following Link: rel=next headers."""
    next_url = url
    next_params = params
    while next_url:
        resp = session.get(next_url, params=next_params, timeout=30)
        resp.raise_for_status()
        for item in resp.json():
            yield item
        next_params = None  # already encoded in the Link header on subsequent calls
        next_url = None
        for link in resp.headers.get("Link", "").split(","):
            link = link.strip()
            if link.endswith('rel="next"') and link.startswith("<"):
                next_url = link[1:link.index(">")]
                break
