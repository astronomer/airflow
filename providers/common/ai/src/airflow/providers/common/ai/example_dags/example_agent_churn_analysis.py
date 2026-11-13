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
"""Example Dag: agents rank renewing customers by churn risk, and each step is evaluated before the next runs."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta

from pydantic import BaseModel, Field

from airflow.providers.common.ai.toolsets.object_storage import ObjectStorageToolset
from airflow.providers.common.ai.toolsets.sql import SQLToolset
from airflow.providers.sqlite.hooks.sqlite import SqliteHook
from airflow.sdk import ObjectStoragePath, dag, task

LLM_CONN_ID = "pydanticai_default"
CRM_CONN_ID = "crm"
WAREHOUSE_CONN_ID = "warehouse"
LEGAL_CONN_ID = "legal_docs"
CONTRACTS_PATH = "file://contracts"

log = logging.getLogger(__name__)


class RenewingCustomer(BaseModel):
    account_id: str
    name: str
    renewal_date: date
    amount: float = Field(gt=0)


class Renewals(BaseModel):
    customers: list[RenewingCustomer]


class CustomerIncidents(BaseModel):
    account_id: str
    incident_ids: list[int] = Field(min_length=1)
    worst_severity: int = Field(ge=1, le=3, description="1 is the most severe.")


class Incidents(BaseModel):
    customers: list[CustomerIncidents]


# [START howto_agent_churn_analysis_output_types]
class SlaCommitment(BaseModel):
    account_id: str
    # A bare file name, because evaluate_slas opens it.
    contract_file: str = Field(pattern=r"^\w[\w.-]*$", description="The file name list_files gave.")
    commitment: str = Field(description="What is promised, in a few words, such as '99.9% monthly uptime'.")
    quote: str = Field(description="The sentence of the contract that makes the promise, word for word.")


class Slas(BaseModel):
    commitments: list[SlaCommitment]


class Priority(BaseModel):
    account_id: str
    score: int = Field(ge=0, le=100, description="100 is the most urgent.")
    reason: str


class Priorities(BaseModel):
    customers: list[Priority]


# [END howto_agent_churn_analysis_output_types]


class Verdict(BaseModel):
    account_id: str
    justified: bool
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def get_quarter(day: date) -> tuple[date, date]:
    """Return the first and last day of the quarter that ``day`` falls in."""
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = date(day.year, first_month, 1)
    if first_month == 10:
        next_start = date(day.year + 1, 1, 1)
    else:
        next_start = date(day.year, first_month + 3, 1)
    return start, next_start - timedelta(days=1)


def find_duplicates(account_ids: list[str]) -> list[str]:
    return sorted(account_id for account_id, count in Counter(account_ids).items() if count > 1)


# [START howto_agent_churn_analysis_evaluate]
class EvaluationFailed(Exception):
    """A step's output failed one or more of the checks run on it."""


def evaluate(checks: dict[str, list[str]]) -> dict[str, str]:
    """
    Log each check, fail the task if any failed, and return the scorecard.

    Each check maps what it verifies to the customers that failed it; an empty list passes.
    """
    failed = []
    for check, failures in checks.items():
        if failures:
            log.error("FAIL  %s: %s", check, ", ".join(failures))
            failed.append(f"{check} (failed for: {', '.join(failures)})")
        else:
            log.info("PASS  %s", check)
    if failed:
        raise EvaluationFailed(f"{len(failed)} of {len(checks)} checks failed: {'; '.join(failed)}")
    return dict.fromkeys(checks, "pass")


# [END howto_agent_churn_analysis_evaluate]


@task
def seed_stand_ins(dag_run=None) -> None:
    """Fill the local stand-ins for the CRM, the warehouse and the legal system. Delete it to use the real ones."""
    start, end = get_quarter(dag_run.run_after.date())
    SqliteHook(sqlite_conn_id=CRM_CONN_ID).run(
        [
            "DROP TABLE IF EXISTS Account",
            "DROP TABLE IF EXISTS Opportunity",
            "CREATE TABLE Account (Id TEXT PRIMARY KEY, Name TEXT)",
            "CREATE TABLE Opportunity"
            " (Id TEXT PRIMARY KEY, AccountId TEXT, Type TEXT, CloseDate TEXT, Amount REAL)",
            "INSERT INTO Account VALUES ('001A', 'Acme Freight'), ('001B', 'Birch Health'),"
            " ('001C', 'Cobalt Retail'), ('001D', 'Delta Mills')",
            "INSERT INTO Opportunity VALUES"
            f" ('006A', '001A', 'Renewal', '{start + timedelta(days=20)}', 240000),"
            f" ('006B', '001B', 'Renewal', '{start + timedelta(days=45)}', 85000),"
            f" ('006C', '001C', 'Renewal', '{end}', 60000),"
            f" ('006D', '001D', 'Renewal', '{end + timedelta(days=30)}', 150000),"
            f" ('006E', '001C', 'New Business', '{start + timedelta(days=10)}', 20000)",
        ]
    )
    SqliteHook(sqlite_conn_id=WAREHOUSE_CONN_ID).run(
        [
            "DROP TABLE IF EXISTS support_incidents",
            "CREATE TABLE support_incidents"
            " (id INTEGER PRIMARY KEY, account_id TEXT, severity INTEGER, opened_on TEXT, summary TEXT)",
            "INSERT INTO support_incidents VALUES"
            f" (101, '001A', 1, '{start - timedelta(days=40)}', 'Tracking API down for six hours'),"
            f" (102, '001A', 2, '{start - timedelta(days=12)}', 'Shipment webhooks delayed'),"
            f" (103, '001B', 3, '{start - timedelta(days=30)}', 'Report export slow'),"
            f" (104, '001D', 1, '{start - timedelta(days=5)}', 'Login outage')",
        ]
    )
    contracts = ObjectStoragePath(CONTRACTS_PATH, conn_id=LEGAL_CONN_ID)
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "001A.txt").write_text(
        "Services Agreement between Acme Freight and the Provider.\n"
        "4.1 The Provider will make the platform available 99.9% of each calendar month.\n"
        "4.2 The Provider will respond to severity 1 incidents within one hour.\n"
    )
    (contracts / "001B.txt").write_text(
        "Order Form for Birch Health.\nSupport is provided on a best-effort basis during business hours.\n"
    )
    (contracts / "001C.txt").write_text("Order Form for Cobalt Retail.\nStandard terms apply.\n")


@task.agent(
    llm_conn_id=LLM_CONN_ID,
    system_prompt=(
        "You find the customers up for renewal in the CRM, whose tables are named after Salesforce "
        "objects: Account and Opportunity. A renewal is an Opportunity whose Type is 'Renewal'."
    ),
    toolsets=[SQLToolset(db_conn_id=CRM_CONN_ID, allowed_tables=["Account", "Opportunity"])],
    output_type=Renewals,
)
def pull_renewals(dag_run=None) -> str:
    start, end = get_quarter(dag_run.run_after.date())
    return (
        f"List every account with a renewal closing from {start} to {end}, "
        "with the account's name, the close date and the amount."
    )


@task(retries=0)
def evaluate_renewals(renewals, dag_run=None):
    customers = Renewals.model_validate(renewals).customers
    start, end = get_quarter(dag_run.run_after.date())
    return evaluate(
        {
            "at least one customer renews this quarter": [] if customers else ["none found"],
            "each renewal closes this quarter": [
                c.account_id for c in customers if not start <= c.renewal_date <= end
            ],
            "no customer is listed twice": find_duplicates([c.account_id for c in customers]),
        }
    )


@task.agent(
    llm_conn_id=LLM_CONN_ID,
    system_prompt=(
        "You look up customers' support incidents in the warehouse's support_incidents table. "
        "Severity 1 is the most severe."
    ),
    toolsets=[SQLToolset(db_conn_id=WAREHOUSE_CONN_ID, allowed_tables=["support_incidents"])],
    output_type=Incidents,
)
def check_incidents(renewals) -> str:
    return (
        "List the customers below that have support incidents, with the incident ids and the worst "
        "severity. Leave out customers with none.\n" + Renewals.model_validate(renewals).model_dump_json()
    )


@task(retries=0)
def evaluate_incidents(renewals, incidents):
    renewing = {c.account_id for c in Renewals.model_validate(renewals).customers}
    found = [c.account_id for c in Incidents.model_validate(incidents).customers]
    return evaluate(
        {
            "each customer with incidents renews this quarter": [a for a in found if a not in renewing],
            "no customer is listed twice": find_duplicates(found),
        }
    )


# [START howto_agent_churn_analysis_step]
@task.agent(
    llm_conn_id=LLM_CONN_ID,
    system_prompt=(
        "You read customer contracts and find their SLA commitments: the uptime, response or "
        "resolution times the Provider promised. A contract's file is named after the account id."
    ),
    toolsets=[ObjectStorageToolset(CONTRACTS_PATH, conn_id=LEGAL_CONN_ID)],
    output_type=Slas,
)
def check_slas(incidents) -> str:
    return (
        "For each customer below, read its contract and list each SLA commitment it makes, quoting the "
        "sentence word for word. Leave out contracts that make none.\n"
        + Incidents.model_validate(incidents).model_dump_json()
    )


@task(retries=0)
def evaluate_slas(incidents, slas):
    with_incidents = {c.account_id for c in Incidents.model_validate(incidents).customers}
    commitments = Slas.model_validate(slas).commitments
    contracts = ObjectStoragePath(CONTRACTS_PATH, conn_id=LEGAL_CONN_ID)

    def is_quoted(commitment: SlaCommitment) -> bool:
        contract = contracts / commitment.contract_file
        if not contract.is_file():
            return False
        return " ".join(commitment.quote.split()) in " ".join(contract.read_text().split())

    return evaluate(
        {
            "each SLA belongs to a customer with incidents": [
                c.account_id for c in commitments if c.account_id not in with_incidents
            ],
            "each quote appears word for word in its contract": [
                c.account_id for c in commitments if not is_quoted(c)
            ],
        }
    )


# [END howto_agent_churn_analysis_step]


def build_evidence(renewals, incidents, slas) -> str:
    return (
        f"Renewals: {Renewals.model_validate(renewals).model_dump_json()}\n"
        f"Incidents: {Incidents.model_validate(incidents).model_dump_json()}\n"
        f"SLA commitments: {Slas.model_validate(slas).model_dump_json()}"
    )


@task.llm(
    llm_conn_id=LLM_CONN_ID,
    system_prompt=(
        "You rank customers up for renewal by how urgently their account team should act to keep them. "
        "Score every customer, using only the evidence given, and say which evidence each score rests on."
    ),
    output_type=Priorities,
)
def score_priorities(renewals, incidents, slas) -> str:
    return build_evidence(renewals, incidents, slas)


# [START howto_agent_churn_analysis_judge]


@task.llm(
    llm_conn_id=LLM_CONN_ID,
    system_prompt=(
        "You review a churn priority list. For each customer, decide whether its score and reason "
        "follow from the evidence. A reason that rests on anything the evidence does not say is not justified."
    ),
    output_type=Verdicts,
)
def judge_priorities(renewals, incidents, slas, priorities) -> str:
    return (
        f"{build_evidence(renewals, incidents, slas)}\n"
        f"Priority list: {Priorities.model_validate(priorities).model_dump_json()}"
    )


@task(retries=0)
def evaluate_priorities(renewals, incidents, priorities, verdicts):
    renewing = {c.account_id for c in Renewals.model_validate(renewals).customers}
    with_incidents = {c.account_id for c in Incidents.model_validate(incidents).customers}
    scored = Priorities.model_validate(priorities).customers
    scores = {p.account_id: p.score for p in scored}
    judged = {v.account_id: v for v in Verdicts.model_validate(verdicts).verdicts}
    lowest_with_incidents = min((s for a, s in scores.items() if a in with_incidents), default=101)
    return evaluate(
        {
            "each renewing customer is scored once": sorted(renewing ^ scores.keys())
            + find_duplicates([p.account_id for p in scored]),
            "customers with incidents score above customers without": sorted(
                a for a, s in scores.items() if a not in with_incidents and s >= lowest_with_incidents
            ),
            "the judge finds each score justified": [
                f"{a} ({v.reason})" for a, v in judged.items() if not v.justified
            ],
            "the judge reviewed each scored customer": sorted(scores.keys() - judged.keys()),
        }
    )


# [END howto_agent_churn_analysis_judge]


# [START howto_agent_churn_analysis_dag]
@dag(tags=["example"])
def example_agent_churn_analysis():
    renewals = pull_renewals()
    incidents = check_incidents(renewals)
    slas = check_slas(incidents)
    priorities = score_priorities(renewals, incidents, slas)
    verdicts = judge_priorities(renewals, incidents, slas, priorities)

    seed_stand_ins() >> renewals
    evaluate_renewals(renewals) >> incidents
    evaluate_incidents(renewals, incidents) >> slas
    evaluate_slas(incidents, slas) >> priorities
    evaluate_priorities(renewals, incidents, priorities, verdicts)


workflow = example_agent_churn_analysis()

if __name__ == "__main__":
    result = workflow.run()
    print(result.output("score_priorities"))
# [END howto_agent_churn_analysis_dag]
