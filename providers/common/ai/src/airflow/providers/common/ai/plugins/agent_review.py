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
"""
A task instance tab that renders an agent's output as prose instead of raw XCom.

An agent returns markdown. The XCom tab shows it as one escaped string, which is unreadable
for anything longer than a sentence. This renders it, and puts the agent's standing context,
what it has learned and what it has spent next to it, so you can see the output and the
inputs that shaped it in one place.

Server-rendered HTML in an iframe, so there is no bundle to build, unlike the React route
``hitl_review`` takes.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlparse

from airflow.plugins_manager import AirflowPlugin
from airflow.providers.common.compat.sdk import conf
from airflow.providers.common.compat.version_compat import AIRFLOW_V_3_1_PLUS

if TYPE_CHECKING:
    from airflow.plugins_manager import ExternalViewDict, FastAPIAppDict

_PLUGIN_PREFIX = "/agent-review"
_AGENT_XCOM_KEY = "airflow_agent_name"
_MEMORY_KEY = "learned"
_SPEND_KEY = "spend"


def _get_base_url_path(path: str) -> str:
    """Prefix a path with the api base_url path, for deployments not served at root."""
    base_url = conf.get("api", "base_url", fallback="/")
    base_path = urlparse(base_url).path if base_url.startswith(("http://", "https://")) else base_url
    return base_path.rstrip("/") + path


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

_INLINE_PATTERNS = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"<em>\1</em>"),
)


def _render_inline(text: str) -> str:
    """Escape, then apply inline markdown. Escaping first, so agent output cannot inject HTML."""
    out = html.escape(text)
    for pattern, replacement in _INLINE_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def render_markdown(text: str) -> str:
    """
    Render the small subset of markdown a model actually emits in a review.

    Headings, bold, italic, inline code, fenced code, bullet and numbered lists, paragraphs.
    Hand rolled rather than pulling in a markdown dependency for one page.
    """
    lines = text.splitlines()
    parts: list[str] = []
    in_code = False
    paragraph: list[str] = []
    # Open lists, outermost first, as (indent, tag). A stack rather than a single tag because
    # models write sub-bullets under numbered points, and treating those as a sibling list
    # restarts the numbering at 1 on every item.
    stack: list[tuple[int, str]] = []
    li_open = False

    def close_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{_render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_li() -> None:
        nonlocal li_open
        if li_open:
            parts.append("</li>")
            li_open = False

    def close_lists(down_to: int = -1) -> None:
        """Close every open list indented deeper than ``down_to``."""
        nonlocal li_open
        while stack and stack[-1][0] > down_to:
            close_li()
            parts.append(f"</{stack.pop()[1]}>")
            # The parent list item is still open around the nested list we just closed.
            li_open = bool(stack)

    def open_item(indent: int, tag: str, content: str) -> None:
        nonlocal li_open
        close_paragraph()
        close_lists(indent)
        if not stack or stack[-1][0] < indent:
            # Nest inside the current item rather than ending it.
            stack.append((indent, tag))
            parts.append(f"<{tag}>")
        elif stack[-1][1] != tag:
            close_li()
            parts.append(f"</{stack.pop()[1]}>")
            stack.append((indent, tag))
            parts.append(f"<{tag}>")
        else:
            close_li()
        parts.append(f"<li>{_render_inline(content)}")
        li_open = True

    def close_list() -> None:
        close_lists()

    for line in lines:
        if line.strip().startswith("```"):
            close_paragraph()
            close_list()
            parts.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            parts.append(html.escape(line))
            continue

        stripped = line.strip()
        if not stripped:
            # A blank line inside a list is a paragraph break, not the end of the list.
            close_paragraph()
            if not stack:
                close_list()
            continue

        indent = len(line) - len(line.lstrip())

        if heading := re.match(r"^(#{1,6})\s+(.*)$", stripped):
            close_paragraph()
            close_list()
            level = min(len(heading.group(1)) + 1, 6)
            parts.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            continue

        if re.match(r"^[-*]{3,}$", stripped):
            close_paragraph()
            close_list()
            parts.append("<hr>")
            continue

        if bullet := re.match(r"^[-*]\s+(.*)$", stripped):
            open_item(indent, "ul", bullet.group(1))
            continue

        if numbered := re.match(r"^\d+[.)]\s+(.*)$", stripped):
            open_item(indent, "ol", numbered.group(1))
            continue

        if not stack:
            close_list()
        paragraph.append(stripped)

    close_paragraph()
    close_list()
    if in_code:
        parts.append("</pre>")
    return "\n".join(parts)


_STYLE = """
:root { color-scheme: light dark; }
body {
  margin: 0; padding: 20px 24px;
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1a202c; background: #fff;
}
h1, h2, h3, h4 { line-height: 1.3; margin: 1.4em 0 .5em; }
h2 { font-size: 1.25em; } h3 { font-size: 1.1em; } h4 { font-size: 1em; }
p, li { margin: .5em 0; }
ul, ol { padding-left: 1.4em; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .89em;
  background: #f1f3f5; padding: .12em .35em; border-radius: 3px;
}
pre {
  background: #f7f8fa; border: 1px solid #e3e6ea; border-radius: 6px;
  padding: 12px 14px; overflow-x: auto; font-size: .85em;
}
pre code { background: none; padding: 0; }
hr { border: 0; border-top: 1px solid #e3e6ea; margin: 1.6em 0; }
.panel { border: 1px solid #e3e6ea; border-radius: 8px; margin-bottom: 20px; }
.panel > summary {
  cursor: pointer; padding: 10px 14px; font-weight: 600; user-select: none;
}
.panel > .body { padding: 0 14px 12px; border-top: 1px solid #e3e6ea; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 0 0 16px; font-size: .88em; }
.meta span { color: #5a6672; }
.meta b { color: #1a202c; font-weight: 600; }
.empty { color: #5a6672; font-style: italic; }
blockquote { margin: 0; padding-left: 12px; border-left: 3px solid #e3e6ea; color: #5a6672; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e9ed; background: #1b1f24; }
  code { background: #2b3138; }
  pre { background: #22272e; border-color: #343a42; }
  .panel, .panel > .body, hr, blockquote { border-color: #343a42; }
  .meta span, .empty, blockquote { color: #9aa5b1; }
  .meta b { color: #e6e9ed; }
}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def _panel(summary: str, body_html: str, *, open_by_default: bool = False) -> str:
    attr = " open" if open_by_default else ""
    return (
        f"<details class='panel'{attr}><summary>{html.escape(summary)}</summary>"
        f"<div class='body'>{body_html}</div></details>"
    )


if AIRFLOW_V_3_1_PLUS:
    from fastapi import Depends, FastAPI, Query
    from fastapi.responses import HTMLResponse
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from airflow._shared.state import AgentScope
    from airflow.api_fastapi.auth.managers.models.resource_details import DagAccessEntity
    from airflow.api_fastapi.core_api.security import requires_access_dag
    from airflow.models.agent import AgentModel
    from airflow.models.xcom import XComModel
    from airflow.state import get_state_backend
    from airflow.utils.session import create_session

    def _get_session():
        with create_session(scoped=False) as session:
            yield session

    SessionDep = Annotated[Session, Depends(_get_session)]

    def _read_xcom(
        session: Session, *, dag_id: str, run_id: str, task_id: str, map_index: int, key: str
    ) -> Any:
        row = session.scalars(
            XComModel.get_many(
                run_id=run_id,
                key=key,
                dag_ids=dag_id,
                task_ids=task_id,
                map_indexes=map_index,
                limit=1,
            )
        ).first()
        return None if row is None else row.value

    def _get_map_index(q: str = Query("-1", alias="map_index")) -> int:
        """Placeholders are substituted by the UI; fall back when unreplaced or invalid."""
        try:
            return int(q)
        except (ValueError, TypeError):
            return -1

    MapIndexDep = Annotated[int, Depends(_get_map_index)]

    agent_review_app = FastAPI(
        title="Agent Review",
        description="Renders an agent task's output as prose, alongside the agent that produced it.",
    )

    @agent_review_app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness check."""
        return {"status": "ok"}

    def _agent_panels(session: Session, agent_name: str) -> str:
        """Render the standing context, learned memory and spend for an agent."""
        agent = session.scalar(select(AgentModel).where(AgentModel.name == agent_name))
        if agent is None:
            return _panel(
                f"Agent: {agent_name}",
                f"<p class='empty'>No agent named {html.escape(agent_name)} exists any more.</p>",
            )

        backend = get_state_backend()
        scope = AgentScope(agent_id=agent.id)
        learned = backend.get(scope, _MEMORY_KEY, session=session)
        spend = backend.get(scope, _SPEND_KEY, session=session)

        import json

        learned_text = json.loads(learned) if learned else ""
        spend_total = (json.loads(spend) or {}).get("total") if spend else None

        meta = (
            "<div class='meta'>"
            f"<span>agent <b>{html.escape(agent.name)}</b></span>"
            f"<span>model <b>{html.escape(agent.model)}</b></span>"
            f"<span>connection <b>{html.escape(agent.conn_id)}</b></span>"
            f"<span>memory <b>{'on' if agent.memory_enabled else 'off'}</b></span>"
            f"<span>spent <b>{f'${spend_total:.6f}' if spend_total is not None else 'not recorded'}</b></span>"
            "</div>"
        )

        context_body = (
            render_markdown(agent.context)
            if agent.context
            else "<p class='empty'>This agent has no standing context.</p>"
        )
        if learned_text:
            lesson_count = sum(1 for line in learned_text.splitlines() if line.startswith("- "))
            learned_body = render_markdown(learned_text)
            learned_summary = f"What it has learned ({lesson_count})"
        else:
            learned_body = (
                "<p class='empty'>Nothing learned yet. This is the normal outcome: a lesson is "
                "only stored when it is not already covered by the standing context.</p>"
            )
            learned_summary = "What it has learned (0)"

        return meta + _panel("Standing context", context_body) + _panel(learned_summary, learned_body)

    @agent_review_app.get(
        "/view",
        response_class=HTMLResponse,
        dependencies=[Depends(requires_access_dag(method="GET", access_entity=DagAccessEntity.XCOM))],
    )
    async def view(
        db: SessionDep,
        dag_id: str,
        task_id: str,
        run_id: str,
        map_index: MapIndexDep,
    ) -> HTMLResponse:
        """Render this task instance's agent output, with the agent that produced it."""
        keys = dict(dag_id=dag_id, run_id=run_id, task_id=task_id, map_index=map_index)
        output = _read_xcom(db, key="return_value", **keys)
        agent_name = _read_xcom(db, key=_AGENT_XCOM_KEY, **keys)

        body = ""
        if agent_name:
            body += _agent_panels(db, str(agent_name))

        if output is None:
            body += (
                "<p class='empty'>No output yet. The task has not finished, or it failed before "
                "returning anything.</p>"
            )
        elif isinstance(output, str):
            body += render_markdown(output)
        else:
            # A structured output_type; show it as-is rather than pretending it is prose.
            import json

            body += f"<pre>{html.escape(json.dumps(output, indent=2, default=str))}</pre>"

        return HTMLResponse(_page(f"{task_id} review", body))


class AgentReviewPlugin(AirflowPlugin):
    """Register the agent review tab on the task instance page."""

    name = "agent_review"
    fastapi_apps: list[FastAPIAppDict] = []
    external_views: list[ExternalViewDict] = []
    if AIRFLOW_V_3_1_PLUS:
        fastapi_apps = [
            {
                "name": "agent-review",
                "app": agent_review_app,
                "url_prefix": _PLUGIN_PREFIX,
            }
        ]
        external_views = [
            {
                "name": "Agent Review",
                "href": _get_base_url_path(
                    f"{_PLUGIN_PREFIX}/view"
                    "?dag_id={DAG_ID}&run_id={RUN_ID}&task_id={TASK_ID}&map_index={MAP_INDEX}"
                ),
                "destination": "task_instance",
                # Only on tasks that could have produced an agent output.
                "applies_to": {"operators": ["AgentOperator", "_AgentDecoratedOperator"]},
            }
        ]
