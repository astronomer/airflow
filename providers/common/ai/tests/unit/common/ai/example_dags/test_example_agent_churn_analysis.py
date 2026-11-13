# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""``example_agent_churn_analysis``: each step's evaluation passes, or a made-up SLA quote stops the run."""

from __future__ import annotations

import json
import re
from unittest import mock

import pytest

pytest.importorskip("airflow.providers.sqlite")

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from airflow.providers.common.ai.example_dags import example_agent_churn_analysis as example
from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook

REAL_QUOTE = "4.1 The Provider will make the platform available 99.9% of each calendar month."
MADE_UP_QUOTE = "The Provider guarantees 99.99% uptime and a full refund for any outage."


def build_scripted_model(sla_quote: str) -> FunctionModel:
    """Answer each step as a model would, reading the tools' results; the SLA step quotes ``sla_quote``."""

    def respond(messages, info: AgentInfo) -> ModelResponse:
        prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        returns = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]

        def listed_account_ids() -> list[str]:
            return [c["account_id"] for c in json.loads(prompt.split("\n", 1)[1])["customers"]]

        def answer(output: dict) -> ModelResponse:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

        if "Salesforce" in info.instructions:
            if not returns:
                start, end = re.search(r"from (\S+) to (\S+),", prompt).groups()
                sql = (
                    "SELECT a.Id, a.Name, o.CloseDate, o.Amount FROM Opportunity o JOIN Account a"
                    f" ON a.Id = o.AccountId WHERE o.Type = 'Renewal' AND o.CloseDate BETWEEN '{start}' AND '{end}'"
                )
                return ModelResponse(parts=[ToolCallPart("query", {"sql": sql})])
            rows = json.loads(returns[0])["rows"]
            keys = ("account_id", "name", "renewal_date", "amount")
            return answer({"customers": [dict(zip(keys, row)) for row in rows]})

        if "support_incidents" in info.instructions:
            if not returns:
                ids = ", ".join(f"'{a}'" for a in listed_account_ids())
                sql = f"SELECT id, account_id, severity FROM support_incidents WHERE account_id IN ({ids})"
                return ModelResponse(parts=[ToolCallPart("query", {"sql": sql})])
            found: dict[str, dict] = {}
            for incident_id, account_id, severity in json.loads(returns[0])["rows"]:
                customer = found.setdefault(account_id, {"incident_ids": [], "worst_severity": severity})
                customer["incident_ids"].append(incident_id)
                customer["worst_severity"] = min(customer["worst_severity"], severity)
            return answer({"customers": [{"account_id": a, **c} for a, c in found.items()]})

        if "contracts" in info.instructions:
            account_ids = listed_account_ids()
            if not returns:
                return ModelResponse(
                    parts=[ToolCallPart("read_file", {"path": f"{a}.txt"}) for a in account_ids]
                )
            commitments = [
                {
                    "account_id": account_id,
                    "contract_file": f"{account_id}.txt",
                    "commitment": "99.9% monthly uptime",
                    "quote": sla_quote,
                }
                for account_id, contract in zip(account_ids, returns)
                if "99.9%" in contract
            ]
            return answer({"commitments": commitments})

        if "rank customers" in info.instructions:
            return answer(
                {
                    "customers": [
                        {"account_id": "001A", "score": 90, "reason": "A severity 1 incident and an SLA."},
                        {"account_id": "001B", "score": 55, "reason": "One severity 3 incident, no SLA."},
                        {"account_id": "001C", "score": 10, "reason": "No incidents."},
                    ]
                }
            )

        verdicts = [
            {"account_id": a, "justified": True, "reason": "Matches the evidence."}
            for a in ("001A", "001B", "001C")
        ]
        return answer({"verdicts": verdicts})

    return FunctionModel(respond)


@pytest.fixture
def connections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for conn_id in ("crm", "warehouse"):
        monkeypatch.setenv(
            f"AIRFLOW_CONN_{conn_id.upper()}",
            json.dumps({"conn_type": "sqlite", "host": str(tmp_path / f"{conn_id}.db")}),
        )
    monkeypatch.setenv(
        "AIRFLOW_CONN_PYDANTICAI_DEFAULT",
        json.dumps({"conn_type": "pydanticai", "extra": {"model": "openai:gpt-5"}}),
    )


def run_dag():
    dag_run = example.workflow.test()
    return dag_run, {ti.task_id: ti.state for ti in dag_run.get_task_instances()}


@pytest.mark.db_test
@pytest.mark.usefixtures("connections")
@mock.patch.object(PydanticAIHook, "get_conn", autospec=True)
def test_every_evaluation_passes(mock_get_conn):
    mock_get_conn.return_value = build_scripted_model(REAL_QUOTE)
    dag_run, states = run_dag()

    assert dag_run.state == "success"
    assert set(states.values()) == {"success"}
    ti = dag_run.get_task_instance("evaluate_priorities")
    assert ti.xcom_pull(task_ids="evaluate_priorities") == {
        "each renewing customer is scored once": "pass",
        "customers with incidents score above customers without": "pass",
        "the judge finds each score justified": "pass",
        "the judge reviewed each scored customer": "pass",
    }


@pytest.mark.db_test
@pytest.mark.usefixtures("connections")
@mock.patch.object(PydanticAIHook, "get_conn", autospec=True)
def test_a_made_up_quote_fails_evaluate_slas_and_stops_the_steps_after_it(mock_get_conn):
    mock_get_conn.return_value = build_scripted_model(MADE_UP_QUOTE)
    dag_run, states = run_dag()

    assert dag_run.state == "failed"
    assert states["evaluate_slas"] == "failed"
    assert {states[t] for t in ("score_priorities", "judge_priorities", "evaluate_priorities")} == {
        "upstream_failed"
    }
    assert {states[t] for t in ("evaluate_renewals", "evaluate_incidents", "check_slas")} == {"success"}
