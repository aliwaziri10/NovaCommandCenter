"""
Render Health Check - polls Render's API for the Nova backend service's
current status, latest deploy, and recent error logs, and writes the
result into Supabase (public.render_status) so it can be checked
without needing the Render dashboard directly.

Requires env vars:
  RENDER_API_KEY   - Render API key (Account Settings -> API Keys)
  RENDER_SERVICE_NAME - the Render service name to look up (must match
                        exactly what's shown in the Render dashboard)
  SUPABASE_URL
  SUPABASE_SECRET_KEY
"""
import os
import sys
import requests

RENDER_API_KEY = os.environ["RENDER_API_KEY"]
RENDER_SERVICE_NAME = os.environ["RENDER_SERVICE_NAME"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}


def find_service():
    resp = requests.get(
        "https://api.render.com/v1/services",
        headers=HEADERS,
        params={"name": RENDER_SERVICE_NAME, "limit": 20},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()
    for item in items:
        svc = item.get("service", item)
        if svc.get("name") == RENDER_SERVICE_NAME:
            return svc
    if items:
        return items[0].get("service", items[0])
    raise RuntimeError(f"No Render service found matching name={RENDER_SERVICE_NAME!r}")


def get_latest_deploy(service_id):
    resp = requests.get(
        f"https://api.render.com/v1/services/{service_id}/deploys",
        headers=HEADERS,
        params={"limit": 1},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        return None
    return items[0].get("deploy", items[0])


def get_recent_logs(owner_id, service_id, limit=50):
    resp = requests.get(
        "https://api.render.com/v1/logs",
        headers=HEADERS,
        params={
            "ownerId": owner_id,
            "resource": [service_id],
            "limit": limit,
            "direction": "backward",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def write_status(service_status=None, latest_deploy_status=None,
                  latest_deploy_created_at=None, recent_error_count=None,
                  log_snippet=None, raw=None):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/render_status",
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json={
            "service_status": service_status,
            "latest_deploy_status": latest_deploy_status,
            "latest_deploy_created_at": latest_deploy_created_at,
            "recent_error_count": recent_error_count,
            "log_snippet": log_snippet,
            "raw": raw,
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        print(f"Supabase write failed: {resp.status_code} {resp.text}")


def main():
    try:
        service = find_service()
    except Exception as e:
        write_status(service_status="lookup_failed", log_snippet=str(e))
        print(f"Service lookup failed: {e}")
        sys.exit(1)

    service_id = service["id"]
    owner_id = service["ownerId"]
    suspended = service.get("suspended", "unknown")

    deploy = None
    try:
        deploy = get_latest_deploy(service_id)
    except Exception as e:
        print(f"Deploy fetch failed: {e}")

    error_count = 0
    log_snippet = ""
    logs = None
    try:
        logs = get_recent_logs(owner_id, service_id)
        entries = logs.get("logs", [])
        error_lines = [
            e for e in entries
            if str(e.get("level", "")).lower() in ("error", "warn", "warning")
            or "error" in str(e.get("message", "")).lower()
        ]
        error_count = len(error_lines)
        log_snippet = "\n".join(
            f"[{e.get('timestamp')}] {e.get('message', '')[:300]}"
            for e in entries[:20]
        )
    except Exception as e:
        print(f"Log fetch failed: {e}")
        log_snippet = f"log fetch failed: {e}"

    write_status(
        service_status=str(suspended),
        latest_deploy_status=deploy.get("status") if deploy else None,
        latest_deploy_created_at=deploy.get("createdAt") if deploy else None,
        recent_error_count=error_count,
        log_snippet=log_snippet,
        raw={"service": service, "deploy": deploy, "logs": logs},
    )
    print(f"Wrote render_status row. service_status={suspended} "
          f"deploy_status={deploy.get('status') if deploy else None} "
          f"recent_error_count={error_count}")


if __name__ == "__main__":
    main()
