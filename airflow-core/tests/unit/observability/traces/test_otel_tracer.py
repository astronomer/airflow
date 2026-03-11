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
from __future__ import annotations

from opentelemetry import trace

from airflow._shared.observability.traces.otel_tracer import OtelTrace
from airflow.observability.trace import Trace


class TestOtelTraceBackcompat:
    """Verify the OtelTrace shim exposes the old API without errors."""

    def test_trace_is_otel_trace_instance(self):
        assert isinstance(Trace, OtelTrace)

    def test_init_accepts_old_kwargs(self):
        OtelTrace(
            span_exporter=None,
            use_simple_processor=True,
            tag_string="foo=bar",
            otel_service="airflow",
            debug=True,
        )

    def test_get_tracer(self):
        tracer = Trace.get_tracer("test_component")
        assert tracer is not None

    def test_get_otel_tracer_provider(self):
        provider = Trace.get_otel_tracer_provider()
        assert provider is trace.get_tracer_provider()

    def test_get_current_span(self):
        span = Trace.get_current_span()
        assert span is trace.get_current_span()

    def test_start_span(self):
        with Trace.start_span(span_name="test_span") as span:
            assert span is not None

    def test_start_root_span(self):
        with Trace.start_root_span(span_name="test_root") as span:
            assert span is not None

    def test_start_child_span(self):
        with Trace.start_child_span(span_name="test_child") as span:
            assert span is not None

    def test_inject_extract_roundtrip(self):
        carrier = Trace.inject()
        assert isinstance(carrier, dict)
        ctx = Trace.extract(carrier)
        assert ctx is not None

    def test_shutdown_is_noop(self):
        Trace.shutdown()
