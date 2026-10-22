"""Plan/deploy/verify AWS baseline through an existing short-lived CLI profile.

No access keys are generated or printed. Default is a local plan; deploy requires --apply.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
STACK = "secure-doc-hybrid-baseline"


class Aws:
    def __init__(self, profile, region):
        self.profile, self.region = profile, region
        self.binary = shutil.which("aws")
        if not self.binary:
            candidate = Path("C:/Program Files/Amazon/AWSCLIV2/aws.exe")
            if candidate.exists():
                self.binary = str(candidate)
        if not self.binary:
            raise RuntimeError(
                "Install AWS CLI v2, then aws login --profile secure-doc-hybrid --region ap-northeast-1"
            )

    def call(self, *args):
        env = dict(
            os.environ,
            AWS_PAGER="",
            AWS_EC2_METADATA_DISABLED="true",
            AWS_CLI_OUTPUT_ENCODING="UTF-8",
            AWS_CLI_FILE_ENCODING="UTF-8",
        )
        result = subprocess.run(
            [
                self.binary,
                "--profile",
                self.profile,
                "--region",
                self.region,
                "--output",
                "json",
                "--no-cli-pager",
                *args,
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            # Provider error bodies may contain sensitive metadata. Inspect CLI locally if needed.
            raise RuntimeError(
                "AWS operation failed: "
                + " ".join(args[:2])
                + "; verify profile permissions/session locally"
            )
        if args[:2] == ("cloudformation", "deploy"):
            return {"completed": True}
        return json.loads(result.stdout) if result.stdout.strip() else {}


def budget_policy_matches(budget, notifications, amount, service=None):
    """Verify scope and exact alert policy, not just notification count."""
    try:
        expected = {
            ("ACTUAL", Decimal(50)),
            ("ACTUAL", Decimal(80)),
            ("ACTUAL", Decimal(100)),
            ("FORECASTED", Decimal(100)),
        }
        observed = {
            (n.get("NotificationType"), Decimal(str(n.get("Threshold"))))
            for n in notifications
            if n.get("ComparisonOperator") == "GREATER_THAN"
            and n.get("ThresholdType", "PERCENTAGE") == "PERCENTAGE"
        }
        return (
            budget.get("BudgetType") == "COST"
            and budget.get("TimeUnit") == "MONTHLY"
            and budget.get("BudgetLimit", {}).get("Unit") == "USD"
            and Decimal(str(budget.get("BudgetLimit", {}).get("Amount")))
            == Decimal(str(amount))
            and budget.get("CostFilters", {})
            == ({"Service": [service]} if service else {})
            and len(notifications) == 4
            and observed == expected
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["plan", "auth", "deploy", "verify", "costs"],
        nargs="?",
        default="plan",
    )
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--allow-root-baseline-once",
        action="store_true",
        help="Explicit user-approved exception for this exact 13-resource template only",
    )
    args = parser.parse_args()
    cfg = dotenv_values(ROOT / ".env.finops")
    profile = args.profile or cfg.get("AWS_PROFILE") or "secure-doc-hybrid"
    region = cfg.get("AWS_REGION") or "ap-northeast-1"
    monthly = cfg.get("AWS_MONTHLY_BUDGET_USD") or "30"
    bedrock = cfg.get("BEDROCK_MONTHLY_BUDGET_USD") or "20"
    email = cfg.get("AWS_BUDGET_EMAIL")
    template = ROOT / "infra/aws/hybrid-baseline.json"
    plan = {
        "profile": profile,
        "region": region,
        "stack": STACK,
        "account_monthly_budget_usd": monthly,
        "bedrock_monthly_budget_usd": bedrock,
        "email_configured": bool(email),
        "template": "infra/aws/hybrid-baseline.json",
        "resource_count": len(json.loads(template.read_text())["Resources"]),
        "creates_compute_or_iam_credentials": False,
        "monthly_bill_hard_cap": False,
    }
    if args.action == "plan" or (args.action == "deploy" and not args.apply):
        print(json.dumps(plan, indent=2))
        return
    aws = Aws(profile, region)
    identity = aws.call("sts", "get-caller-identity")
    account = identity["Account"]
    if args.action == "auth":
        print(
            json.dumps(
                {
                    "authenticated": True,
                    "profile": profile,
                    "region": region,
                    "identity_type": "root"
                    if identity["Arn"].endswith(":root")
                    else "iam_or_federated",
                }
            )
        )
        return
    if identity["Arn"].endswith(":root") and args.action == "deploy":
        approved_hash = (
            "9f3af61c05affcb03dafb3418732afa67673819fe19cb6a1f1567f21c47a7b73"
        )
        if (
            not args.allow_root_baseline_once
            or hashlib.sha256(template.read_bytes()).hexdigest() != approved_hash
        ):
            raise RuntimeError(
                "Root deployment blocked: use IAM or explicit approval for the exact baseline template"
            )
    out = ROOT / ".aws-local"
    out.mkdir(exist_ok=True)
    if args.action == "deploy":
        if region != "ap-northeast-1":
            raise ValueError("This portfolio deployment is scoped to Tokyo")
        if not email:
            raise ValueError("Set AWS_BUDGET_EMAIL in ignored .env.finops")
        aws.call(
            "cloudformation",
            "validate-template",
            "--template-body",
            "file://" + template.as_posix(),
        )
        params = out / "parameters.json"
        params.write_text(
            json.dumps(
                [
                    {"ParameterKey": key, "ParameterValue": value}
                    for key, value in [
                        ("BudgetEmail", email),
                        ("MonthlyBudgetUsd", monthly),
                        ("BedrockBudgetUsd", bedrock),
                    ]
                ]
            ),
            encoding="utf8",
        )
        try:
            aws.call(
                "cloudformation",
                "deploy",
                "--stack-name",
                STACK,
                "--template-file",
                str(template),
                "--parameter-overrides",
                "file://" + params.as_posix(),
                "--no-fail-on-empty-changeset",
                "--tags",
                "Project=SecureDoc",
                "Environment=portfolio",
                "ManagedBy=CloudFormation",
            )
        finally:
            params.unlink(missing_ok=True)
        args.action = "verify"
    if args.action == "verify":
        stacks = aws.call("cloudformation", "describe-stacks", "--stack-name", STACK)[
            "Stacks"
        ]
        stack = stacks[0]
        if stack["StackStatus"] not in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            raise RuntimeError("Stack is not complete: " + stack["StackStatus"])
        checks = {"stack_complete": True}
        for name in ("account", "bedrock"):
            budget = aws.call(
                "budgets",
                "describe-budget",
                "--account-id",
                account,
                "--budget-name",
                "secure-doc-hybrid-" + name,
            )["Budget"]
            notifications = aws.call(
                "budgets",
                "describe-notifications-for-budget",
                "--account-id",
                account,
                "--budget-name",
                budget["BudgetName"],
            )["Notifications"]
            checks[name + "_budget"] = float(budget["BudgetLimit"]["Amount"]) == float(
                monthly if name == "account" else bedrock
            )
            checks[name + "_notifications"] = len(notifications) == 4
            checks[name + "_policy"] = budget_policy_matches(
                budget,
                notifications,
                monthly if name == "account" else bedrock,
                "Amazon Bedrock" if name == "bedrock" else None,
            )
            subscribers_ok = True
            for notification in notifications:
                subscribers = aws.call(
                    "budgets",
                    "describe-subscribers-for-notification",
                    "--account-id",
                    account,
                    "--budget-name",
                    budget["BudgetName"],
                    "--notification",
                    json.dumps(notification),
                )["Subscribers"]
                subscribers_ok &= any(
                    s["SubscriptionType"] == "EMAIL" and s["Address"] == email
                    for s in subscribers
                )
            checks[name + "_email"] = subscribers_ok
        bucket = "secure-doc-hybrid-" + account + "-" + region + "-artifacts"
        checks["s3_private"] = all(
            aws.call("s3api", "get-public-access-block", "--bucket", bucket)[
                "PublicAccessBlockConfiguration"
            ].values()
        )
        checks["s3_versioned"] = (
            aws.call("s3api", "get-bucket-versioning", "--bucket", bucket).get("Status")
            == "Enabled"
        )
        checks["s3_encrypted"] = bool(
            aws.call("s3api", "get-bucket-encryption", "--bucket", bucket)[
                "ServerSideEncryptionConfiguration"
            ]
        )
        for name in ("identity", "knowledge", "conversation", "gateway"):
            repository = aws.call(
                "ecr",
                "describe-repositories",
                "--repository-names",
                "secure-doc-hybrid/" + name,
            )["repositories"][0]
            checks["ecr_" + name] = (
                repository["imageTagMutability"] == "IMMUTABLE"
                and repository["imageScanningConfiguration"]["scanOnPush"]
            )
        logs = aws.call(
            "logs",
            "describe-log-groups",
            "--log-group-name-prefix",
            "/securedoc/hybrid/operations",
        )["logGroups"]
        checks["logs_retention_14_days"] = any(
            g["logGroupName"] == "/securedoc/hybrid/operations"
            and g.get("retentionInDays") == 14
            for g in logs
        )
        alarms = aws.call(
            "cloudwatch", "describe-alarms", "--alarm-name-prefix", "secure-doc-hybrid-"
        )["MetricAlarms"]
        checks["mantle_alarms"] = (
            sum(a.get("Namespace") == "AWS/BedrockMantle" for a in alarms) == 3
        )
        report = {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "passed": all(checks.values()),
            "checks": checks,
        }
        (out / "aws-verification.json").write_text(
            json.dumps(report, indent=2), encoding="utf8"
        )
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
    if args.action == "costs":
        now = datetime.now(timezone.utc)
        if now.day == 1:
            print(
                "No complete UTC day in the current month yet; use billing console for current usage."
            )
            return
        # Billing result is estimated and can lag. Cost Explorer API itself can incur query charges.
        result = aws.call(
            "ce",
            "get-cost-and-usage",
            "--time-period",
            json.dumps(
                {"Start": now.strftime("%Y-%m-01"), "End": now.strftime("%Y-%m-%d")}
            ),
            "--granularity",
            "MONTHLY",
            "--metrics",
            "UnblendedCost",
            "--group-by",
            json.dumps([{"Type": "DIMENSION", "Key": "SERVICE"}]),
        )
        (out / "monthly-service-costs.json").write_text(
            json.dumps(result, indent=2), encoding="utf8"
        )
        print(
            "Billing report saved to .aws-local/monthly-service-costs.json (estimated; API query charges may apply)."
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        raise SystemExit(1) from None
