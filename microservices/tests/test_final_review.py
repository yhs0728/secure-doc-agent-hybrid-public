"""Final review regressions: billing scope, private errors and provisioning safety."""

import logging
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from conversation_service import finops
from conversation_service.graph.nodes import citation_filter_node
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from aws_finops import budget_policy_matches


def test_parser_failure_does_not_log_provider_output(caplog):
    secret = "PRIVATE-DOCUMENT-SENTINEL"
    with caplog.at_level(logging.DEBUG, logger="conversation_service.graph.nodes"):
        result = citation_filter_node(
            {
                "question": "synthetic",
                "answer": "synthetic",
                "documents": [
                    Document(page_content="synthetic", metadata={"source": "test.txt"})
                ],
            },
            FakeListChatModel(responses=[secret]),
        )
    assert result == {"citations": []}
    assert "OutputParserException" in caplog.text
    assert secret not in caplog.text


@pytest.mark.parametrize("value", [0, -1, 1025, True, 1.5])
def test_invalid_reservation_does_not_touch_redis(value):
    client = Mock()
    with pytest.raises(ValueError, match="token cap"):
        finops.Ledger(client).reserve("synthetic", value)
    client.time.assert_not_called()
    client.eval.assert_not_called()


@pytest.mark.parametrize("status", [403, 404, 503, None])
def test_worker_only_creates_a_missing_bucket(status, monkeypatch):
    from knowledge_service import worker

    store = Mock()
    error = (
        ClientError(
            {
                "Error": {"Code": str(status)},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "HeadBucket",
        )
        if status
        else EndpointConnectionError(endpoint_url="http://synthetic.invalid")
    )
    store.head_bucket.side_effect = error
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    monkeypatch.setattr(worker, "migrate", lambda: None)
    monkeypatch.setattr(worker, "run_once", lambda: False)
    monkeypatch.setattr(worker.storage, "object_store", lambda: store)
    monkeypatch.setattr(worker.storage, "bucket", lambda: "synthetic")
    if status == 404:
        worker.main()
        store.create_bucket.assert_called_once_with(Bucket="synthetic")
    else:
        with pytest.raises(type(error)):
            worker.main()
        store.create_bucket.assert_not_called()


def policy():
    budget = {
        "BudgetType": "COST",
        "TimeUnit": "MONTHLY",
        "BudgetLimit": {"Unit": "USD", "Amount": "20"},
        "CostFilters": {"Service": ["Amazon Bedrock"]},
    }
    notifications = [
        {
            "NotificationType": typ,
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": value,
            "ThresholdType": "PERCENTAGE",
        }
        for typ, value in [
            ("ACTUAL", 50),
            ("ACTUAL", 80),
            ("ACTUAL", 100),
            ("FORECASTED", 100),
        ]
    ]
    return budget, notifications


def test_expected_budget_policy_matches():
    budget, notifications = policy()
    assert budget_policy_matches(budget, notifications, "20", "Amazon Bedrock")


@pytest.mark.parametrize(
    "change",
    ["threshold", "type", "unit", "scope", "monthly", "malformed", "duplicate"],
)
def test_budget_policy_detects_wrong_settings(change):
    budget, notifications = policy()
    if change == "threshold":
        notifications[0]["Threshold"] = 99
    elif change == "type":
        notifications[0]["ThresholdType"] = "ABSOLUTE_VALUE"
    elif change == "unit":
        budget["BudgetLimit"]["Unit"] = "EUR"
    elif change == "scope":
        budget["CostFilters"] = {}
    elif change == "monthly":
        budget["TimeUnit"] = "DAILY"
    elif change == "malformed":
        notifications[0]["Threshold"] = "invalid"
    elif change == "duplicate":
        notifications[0] = dict(notifications[1])
    assert not budget_policy_matches(budget, notifications, "20", "Amazon Bedrock")
