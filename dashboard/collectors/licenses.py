"""Orchestrate license collectors across Okta, GWS, and Slack."""

from __future__ import annotations

from datetime import datetime, timezone

from dashboard.collectors import gws, okta, slack
from dashboard.config import load_license_limits


def collect_all_licenses() -> dict:
    limits = load_license_limits()
    services = [
        okta.collect_okta_license(limits["okta"]["purchased"]),
        gws.collect_gws_product(
            "gws_workspace",
            limits["gws_workspace"]["label"],
            limits["gws_workspace"]["productId"],
            limits["gws_workspace"]["purchased"],
        ),
        gws.collect_gws_product(
            "gws_cloud_identity",
            limits["gws_cloud_identity"]["label"],
            limits["gws_cloud_identity"]["productId"],
            limits["gws_cloud_identity"]["purchased"],
        ),
        slack.collect_slack_license(limits["slack"]["purchased"]),
    ]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }


def collect_health() -> dict:
    services = {
        "okta": okta.okta_health(),
        "gws": gws.gws_health(),
        "slack": slack.slack_health(),
    }
    return {"ok": all(v == "ok" for v in services.values()), "services": services}
