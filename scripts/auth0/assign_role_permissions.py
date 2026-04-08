#!/usr/bin/env python3
"""
Assign permissions to Auth0 roles based on a least-privilege permission matrix.

Completes the RBAC architecture: users → roles → permissions → resource server.
When a user authenticates, their access token includes the scopes from their
role's permissions on the NovaTech Internal API.

Prerequisites:
  1. pip install auth0-python python-dotenv
  2. Auth0 M2M credentials in .env
  3. Resource server "NovaTech Internal API" must exist with permissions defined
  4. Roles must exist (created by provision_users.py)

Usage:
  python assign_role_permissions.py --dry-run    # Preview assignments
  python assign_role_permissions.py              # Execute assignments
  python assign_role_permissions.py --verify     # List current permissions per role
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    from auth0.management import Auth0
    from auth0.authentication import GetToken
except ImportError:
    print("ERROR: auth0-python not installed. Run: pip install auth0-python")
    sys.exit(1)

# --- Configuration ---

RESOURCE_SERVER_IDENTIFIER = "https://api.novatech.io"

# Permission-to-role matrix (least-privilege design)
# Design principles:
#   - No role gets access:production by default (requires elevated approval)
#   - it-admin gets manage:* but NOT access:production or write:databases
#   - read:reports is broadly granted; sensitive reports are restricted
#   - Engineering gets write:repos but Data doesn't (they read code, not write it)
ROLE_PERMISSIONS = {
    "engineer": [
        "read:repos",
        "write:repos",
        "access:staging",
        "access:ci-cd",
        "read:databases",
        "read:reports",
        "read:analytics",
    ],
    "data-engineer": [
        "read:repos",
        "read:databases",
        "write:databases",
        "access:pipelines",
        "access:ml-models",
        "read:analytics",
        "read:reports",
    ],
    "it-admin": [
        "manage:users",
        "manage:roles",
        "manage:devices",
        "read:logs",
        "manage:infrastructure",
        "read:reports",
        "read:repos",
    ],
    "finance": [
        "read:billing",
        "approve:expenses",
        "read:reports",
        "read:compensation",
    ],
    "executive": [
        "read:strategic-reports",
        "approve:budgets",
        "read:billing",
        "read:analytics",
        "read:reports",
    ],
    "product": [
        "manage:products",
        "read:user-research",
        "read:analytics",
        "read:reports",
    ],
    "designer": [
        "manage:design-assets",
        "read:design-assets",
        "read:user-research",
        "read:analytics",
    ],
    "hr": [
        "manage:employees",
        "read:compensation",
        "read:reports",
    ],
    "sales": [
        "read:crm",
        "write:crm",
        "read:reports",
        "read:analytics",
    ],
    "marketing": [
        "manage:campaigns",
        "manage:content",
        "read:analytics",
        "read:crm",
        "read:reports",
    ],
}


def get_management_client():
    """Authenticate and return an Auth0 Management API client."""
    domain = os.getenv("AUTH0_DOMAIN")
    client_id = os.getenv("AUTH0_CLIENT_ID")
    client_secret = os.getenv("AUTH0_CLIENT_SECRET")

    if not all([domain, client_id, client_secret]):
        print("ERROR: Missing Auth0 credentials in .env file.")
        sys.exit(1)

    get_token = GetToken(domain, client_id, client_secret=client_secret)
    token = get_token.client_credentials(f"https://{domain}/api/v2/")
    return Auth0(tenant_domain=domain, token=token["access_token"])


def get_role_map(auth0_client):
    """Fetch role name → role ID mapping."""
    result = auth0_client.roles.list()
    if hasattr(result, "roles"):
        roles = result.roles
    elif isinstance(result, dict):
        roles = result.get("roles", [])
    else:
        roles = list(result)

    role_map = {}
    for r in roles:
        name = r["name"] if isinstance(r, dict) else r.name
        rid = r["id"] if isinstance(r, dict) else r.id
        role_map[name] = rid
    return role_map


def verify_resource_server(auth0_client):
    """Verify the resource server exists and list its permissions."""
    try:
        result = auth0_client.resource_servers.list()
        servers = result.get("resource_servers", []) if isinstance(result, dict) else list(result)
        for s in servers:
            identifier = s["identifier"] if isinstance(s, dict) else getattr(s, "identifier", "")
            if identifier == RESOURCE_SERVER_IDENTIFIER:
                scopes = s.get("scopes", []) if isinstance(s, dict) else getattr(s, "scopes", [])
                return [sc["value"] if isinstance(sc, dict) else getattr(sc, "value") for sc in scopes]
        print(f"ERROR: Resource server '{RESOURCE_SERVER_IDENTIFIER}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not fetch resource servers — {e}")
        sys.exit(1)


def assign_permissions(auth0_client, role_id, role_name, permissions, dry_run=False):
    """Assign permissions to a role."""
    perm_bodies = [
        {
            "resource_server_identifier": RESOURCE_SERVER_IDENTIFIER,
            "permission_name": p,
        }
        for p in permissions
    ]

    if dry_run:
        for p in permissions:
            print(f"    [DRY RUN] {p}")
        return True

    try:
        auth0_client.roles.permissions.add(id=role_id, permissions=perm_bodies)
        for p in permissions:
            print(f"    {p}")
        return True
    except Exception as e:
        print(f"    FAILED — {e}")
        return False


def verify_role_permissions(auth0_client, role_map):
    """List current permissions for each role."""
    print("\nCurrent Role Permissions:")
    print("=" * 60)
    for role_name, role_id in sorted(role_map.items()):
        if role_name not in ROLE_PERMISSIONS:
            continue
        try:
            result = auth0_client.roles.permissions.list(role_id)
            perms = list(result)

            perm_names = []
            for p in perms:
                name = p["permission_name"] if isinstance(p, dict) else p.permission_name
                perm_names.append(name)

            expected = set(ROLE_PERMISSIONS[role_name])
            actual = set(perm_names)
            match = "OK" if actual == expected else "DRIFT"

            print(f"\n  {role_name} ({len(perm_names)} permissions) [{match}]")
            for p in sorted(perm_names):
                print(f"    {p}")

            if actual != expected:
                missing = expected - actual
                extra = actual - expected
                if missing:
                    print(f"    MISSING: {', '.join(sorted(missing))}")
                if extra:
                    print(f"    EXTRA: {', '.join(sorted(extra))}")

        except Exception as e:
            print(f"\n  {role_name}: ERROR — {e}")

    print(f"\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="Assign permissions to Auth0 roles (least-privilege RBAC)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without assigning")
    parser.add_argument("--verify", action="store_true", help="List current permissions per role")
    args = parser.parse_args()

    print("Auth0 RBAC: Permission-to-Role Assignment")
    print(f"Resource Server: {RESOURCE_SERVER_IDENTIFIER}")
    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***")
    print()

    # Connect
    auth0_client = get_management_client()
    print("Connected to Auth0 Management API")

    # Get role mapping
    role_map = get_role_map(auth0_client)
    print(f"Found {len(role_map)} roles")

    # Verify-only mode
    if args.verify:
        verify_role_permissions(auth0_client, role_map)
        return

    # Verify resource server exists and get available permissions
    print("Verifying resource server...")
    available_permissions = verify_resource_server(auth0_client)
    print(f"Resource server has {len(available_permissions)} permissions defined\n")

    # Validate matrix against available permissions
    all_matrix_perms = set()
    for perms in ROLE_PERMISSIONS.values():
        all_matrix_perms.update(perms)

    missing_from_server = all_matrix_perms - set(available_permissions)
    if missing_from_server:
        print(f"WARNING: These permissions are in the matrix but not on the resource server:")
        for p in sorted(missing_from_server):
            print(f"  {p}")
        print()

    # Assign permissions
    success = 0
    failed = 0

    for role_name, permissions in ROLE_PERMISSIONS.items():
        role_id = role_map.get(role_name)
        if not role_id:
            print(f"  SKIP: Role '{role_name}' not found in Auth0")
            failed += 1
            continue

        print(f"  {role_name} ({len(permissions)} permissions):")
        if assign_permissions(auth0_client, role_id, role_name, permissions, args.dry_run):
            success += 1
        else:
            failed += 1

    # Summary
    total_perms = sum(len(p) for p in ROLE_PERMISSIONS.values())
    print(f"\n{'=' * 50}")
    print(f"PERMISSION ASSIGNMENT COMPLETE")
    print(f"  Roles configured: {success}")
    print(f"  Roles failed:     {failed}")
    print(f"  Total permissions: {total_perms} across {success + failed} roles")
    print(f"\nPermission matrix summary:")
    for role_name, perms in sorted(ROLE_PERMISSIONS.items()):
        print(f"  {role_name}: {len(perms)} permissions")
    print(f"{'=' * 50}")

    if not args.dry_run:
        print("\nRun with --verify to confirm assignments.")


if __name__ == "__main__":
    main()
