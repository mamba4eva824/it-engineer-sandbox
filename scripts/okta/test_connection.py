#!/usr/bin/env python3
"""Smoke-test Okta Management API credentials.

Fetches a fresh Private Key JWT access token, prints the scopes Okta actually
granted (vs. what we requested), and does a couple of read-only calls so we
know the token works beyond the /token endpoint.

Usage:
  python scripts/okta/test_connection.py
"""

import sys

from _client import OKTA_ORG_URL, OKTA_SCOPES, api_url, get_session


def main():
    print(f"Okta Org URL:    {OKTA_ORG_URL}")
    print(f"Scopes (req'd):  {OKTA_SCOPES}")

    session, granted = get_session()
    print(f"Scopes (granted): {granted}\n")

    missing = set(OKTA_SCOPES.split()) - set(granted.split())
    if missing:
        print("WARNING: these scopes were requested but NOT granted:")
        for s in sorted(missing):
            print(f"  - {s}")
        print("Enable them in Okta Admin Console → API Services app → Okta API Scopes.\n")

    # Prove the token actually works
    for label, path in (("groups", "/api/v1/groups?limit=1"),
                        ("users",  "/api/v1/users?limit=1"),
                        ("schema", "/api/v1/meta/schemas/user/default")):
        resp = session.get(api_url(path), timeout=10)
        ok = "OK" if resp.status_code == 200 else f"FAIL {resp.status_code}"
        print(f"  GET {path:50s} {ok}")
        if resp.status_code != 200:
            sys.exit(1)

    print("\nConnection healthy.")


if __name__ == "__main__":
    main()
