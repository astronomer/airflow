#
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
Backward-compatible OtelTrace shim.

Users should now use the standard OpenTelemetry API directly::

    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)

This module only exists so that code written against the old
``Trace.start_span(...)`` / ``Trace.get_tracer(...)`` API continues
to work without raising errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

if TYPE_CHECKING:
    from opentelemetry.context.context import Context
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span, Tracer


class OtelTrace:
    """Backward-compatible wrapper that delegates to the global OpenTelemetry API."""

    def __init__(self, *args, **kwargs):
        pass

    def shutdown(self):
        pass

    def get_otel_tracer_provider(
        self,
        trace_id: int | None = None,
        span_id: int | None = None,
    ) -> TracerProvider:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    def get_tracer(
        self,
        component: str,
        trace_id: int | None = None,
        span_id: int | None = None,
    ) -> Tracer:
        return trace.get_tracer(component)

    def get_current_span(self) -> Span:
        return trace.get_current_span()

    def use_span(self, span):
        return trace.use_span(span=span)

    def start_span(
        self,
        span_name: str,
        component: str | None = None,
        parent_sc=None,
        span_id=None,
        links=None,
        start_time=None,
    ):
        tracer = self.get_tracer(component or __name__)
        return tracer.start_as_current_span(span_name)

    def start_root_span(
        self,
        span_name: str = "",
        component: str | None = None,
        links=None,
        start_time=None,
        start_as_current: bool = True,
    ):
        tracer = self.get_tracer(component or __name__)
        if start_as_current:
            return tracer.start_as_current_span(span_name)
        return tracer.start_span(span_name)

    def start_child_span(
        self,
        span_name: str = "",
        parent_context: Context | None = None,
        component: str | None = None,
        links=None,
        start_time=None,
        start_as_current: bool = True,
    ):
        tracer = self.get_tracer(component or __name__)
        if start_as_current:
            return tracer.start_as_current_span(span_name, context=parent_context)
        return tracer.start_span(span_name, context=parent_context)

    def inject(self) -> dict:
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        return carrier

    def extract(self, carrier: dict) -> Context:
        return TraceContextTextMapPropagator().extract(carrier)
