"""Verify live local monitoring without printing credentials or payload content."""

import json
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    cfg = dotenv_values(ROOT / ".env.microservices")
    checks = {}
    with httpx.Client(timeout=10, trust_env=False) as client:
        targets = (
            client.get("http://127.0.0.1:29202/api/v1/targets")
            .raise_for_status()
            .json()["data"]["activeTargets"]
        )
        checks["three_services_scraped"] = len(targets) == 3 and all(
            t["health"] == "up" for t in targets
        )
        rules = (
            client.get("http://127.0.0.1:29202/api/v1/rules")
            .raise_for_status()
            .json()["data"]["groups"]
        )
        names = {r["name"] for g in rules for r in g["rules"]}
        checks["finops_alert_rules"] = {
            "SecureDocFinOpsControlUnavailable",
            "SecureDocFinOpsDailyUsage",
        } <= names
        values = (
            client.get(
                "http://127.0.0.1:29202/api/v1/query",
                params={"query": "secure_doc_finops_enabled"},
            )
            .raise_for_status()
            .json()["data"]["result"]
        )
        checks["live_finops_metric"] = any(v["value"][1] == "1" for v in values)
        auth = (cfg.get("GRAFANA_ADMIN_USER") or "admin", cfg["GRAFANA_ADMIN_PASSWORD"])
        dashboard = (
            client.get(
                "http://127.0.0.1:13102/api/dashboards/uid/secure-doc-hybrid-finops",
                auth=auth,
            )
            .raise_for_status()
            .json()["dashboard"]
        )
        checks["grafana_dashboard_seven_panels"] = len(dashboard["panels"]) == 7
        query = (
            client.get(
                "http://127.0.0.1:13102/api/datasources/proxy/uid/prometheus/api/v1/query",
                params={"query": "secure_doc_finops_available"},
                auth=auth,
            )
            .raise_for_status()
            .json()["data"]["result"]
        )
        checks["grafana_datasource_real_values"] = any(
            v["value"][1] == "1" for v in query
        )
        checks["alertmanager_ready"] = (
            client.get("http://127.0.0.1:29302/-/ready").status_code == 200
        )
        checks["grafana_requires_login"] = client.get(
            "http://127.0.0.1:13102/api/dashboards/uid/secure-doc-hybrid-finops"
        ).status_code in (401, 403)
    report = {"passed": all(checks.values()), "checks": checks}
    (ROOT / ".microservice-tests/monitoring-verification.json").write_text(
        json.dumps(report, indent=2), encoding="utf8"
    )
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
