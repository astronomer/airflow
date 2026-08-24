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

import importlib.util
import logging
import os
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest
from opentelemetry import metrics
from opentelemetry.metrics import MeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.view import (
    ExplicitBucketHistogramAggregation,
    ExponentialBucketHistogramAggregation,
    View,
)

from airflow_shared.observability.common import get_otel_data_exporter
from airflow_shared.observability.metrics import otel_logger as otel_logger_module
from airflow_shared.observability.metrics.otel_logger import (
    _OWNER_PID_ATTR,
    OTEL_NAME_MAX_LENGTH,
    UP_DOWN_COUNTERS,
    MetricsMap,
    SafeOtelLogger,
    _generate_key_name,
    _is_up_down_counter,
    full_name,
    get_otel_logger,
)
from airflow_shared.observability.metrics.validators import (
    BACK_COMPAT_METRIC_NAMES,
    MetricNameLengthExemptionWarning,
)
from airflow_shared.observability.otel_env_config import load_metrics_env_config

from tests_common.test_utils.config import env_vars

INVALID_STAT_NAME_CASES = [
    (None, "can not be None"),
    (42, "is not a string"),
    ("X" * OTEL_NAME_MAX_LENGTH, "too long"),
    ("test/$tats", "contains invalid characters"),
]

RATE_MUST_BE_POSITIVE_MSG = "rate must be a positive value"


@pytest.fixture
def name():
    return "test_stats_run"


@pytest.fixture
def reset_meter_provider():
    """Let a test install its own global MeterProvider, then restore the previous one.

    ``set_meter_provider`` is guarded by a process-wide ``Once``, so tests that install a
    provider have to clear it the same way ``get_otel_logger`` does after a fork.
    """
    import opentelemetry.metrics._internal as metrics_internal

    def clear() -> None:
        metrics_internal._METER_PROVIDER_SET_ONCE._done = False
        metrics_internal._METER_PROVIDER = None

    previous = metrics_internal._METER_PROVIDER
    clear()
    yield
    clear()
    metrics_internal._METER_PROVIDER = previous


class TestOtelMetrics:
    def setup_method(self):
        self.meter = mock.Mock(MeterProvider)
        self.stats = SafeOtelLogger(otel_provider=self.meter)
        self.map = self.stats.metrics_map.map
        self.logger = logging.getLogger(__name__)

    def test_is_up_down_counter_positive(self):
        udc = next(iter(UP_DOWN_COUNTERS))

        assert _is_up_down_counter(udc)

    def test_is_up_down_counter_negative(self):
        assert not _is_up_down_counter("this_is_not_a_udc")

    def test_exemption_list_has_not_grown(self):
        assert len(BACK_COMPAT_METRIC_NAMES) <= 25, (
            "This test exists solely to ensure that nobody is adding names to the exemption list. "
            "There are 25 names which are potentially too long for OTel and that number should "
            "only ever go down as these names are deprecated.  If this test is failing, please "
            "adjust your new stat's name; do not add as exemption without a very good reason."
        )

    @pytest.mark.parametrize(
        "invalid_stat_combo",
        [
            *[
                pytest.param(("prefix", name), id=f"Stat name {msg}.")
                for (name, msg) in INVALID_STAT_NAME_CASES
            ],
            *[
                pytest.param((prefix, "name"), id=f"Stat prefix {msg}.")
                for (prefix, msg) in INVALID_STAT_NAME_CASES
            ],
        ],
    )
    def test_invalid_stat_names_are_skipped(self, invalid_stat_combo):
        prefix = invalid_stat_combo[0]
        name = invalid_stat_combo[1]
        self.stats.prefix = prefix

        result = self.stats.incr(name)

        assert result is None
        self.meter.get_meter().create_counter.assert_not_called()

    @pytest.mark.parametrize(
        "stat",
        [
            "dag.my_dag.preço_task.scheduled_duration",
            "dag.my_dag.tâche_principale.duration",
            "dag.my_dag.aufgäbe.duration",
        ],
    )
    def test_non_ascii_stat_names_are_skipped_without_raising(self, stat):
        result = self.stats.incr(stat)

        assert result is None
        self.meter.get_meter().create_counter.assert_not_called()

    @pytest.mark.parametrize(
        "stat",
        [
            "dag_processing.last_run.seconds_ago.PBI_SKU_Performance copy",  # space in filename
            "dag_processing.last_run.seconds_ago.mein_däg_file",  # non-ASCII in filename
        ],
    )
    def test_gauge_with_invalid_stat_names_skipped_without_raising(self, stat):
        self.stats.gauge(stat, value=1)

        self.meter.get_meter().create_gauge.assert_not_called()

    @pytest.mark.parametrize(
        "stat",
        [
            "dag.my_dag.preço_task.duration",  # non-ASCII
            "dag.my_dag.task copy.duration",  # space
        ],
    )
    def test_timer_with_invalid_stat_name_does_not_record(self, stat):
        with self.stats.timer(stat):
            pass

        self.meter.get_meter().create_histogram.assert_not_called()

    def test_old_name_exception_works(self, caplog):
        name = "task_instance_created_OperatorNameWhichIsSuperLongAndExceedsTheOpenTelemetryCharacterLimit/task_instance_created_OperatorNameWhichIsSuperLongAndExceedsTheOpenTelemetryCharacterLimit/task_instance_created_OperatorNameWhichIsSuperLongAndExceedsTheOpenTelemetryCharacterLimit"

        assert len(name) > OTEL_NAME_MAX_LENGTH

        with pytest.warns(MetricNameLengthExemptionWarning):
            self.stats.incr(name)

        self.meter.get_meter().create_counter.assert_called_once_with(
            name=(full_name(name)[:OTEL_NAME_MAX_LENGTH])
        )

    def test_incr_new_metric(self, name):
        self.stats.incr(name)

        self.meter.get_meter().create_counter.assert_called_once_with(name=full_name(name))

    def test_incr_new_metric_with_tags(self, name):
        tags = {"hello": "world"}
        key = _generate_key_name(full_name(name), tags)

        self.stats.incr(name, tags=tags)

        self.meter.get_meter().create_counter.assert_called_once_with(name=full_name(name))
        self.map[key].add.assert_called_once_with(1, attributes=tags)

    def test_incr_existing_metric(self, name):
        # Create the metric and set value to 1
        self.stats.incr(name)
        # Increment value to 2
        self.stats.incr(name)

        assert self.map[full_name(name)].add.call_count == 2
        self.meter.get_meter().create_counter.assert_called_once_with(name=full_name(name))

    @mock.patch("random.random", side_effect=[0.1, 0.9])
    def test_incr_with_rate_limit_works(self, mock_random, name):
        # Create the counter and set the value to 1
        self.stats.incr(name, rate=0.5)
        # This one should not increment because random() will return a value higher than `rate`
        self.stats.incr(name, rate=0.5)
        # This one should raise an exception for a negative `rate` value
        with pytest.raises(ValueError, match=RATE_MUST_BE_POSITIVE_MSG):
            self.stats.incr(name, rate=-0.5)

        assert mock_random.call_count == 2
        assert self.map[full_name(name)].add.call_count == 1

    def test_decr_existing_metric(self, name):
        expected_calls = [
            mock.call(1, attributes=None),
            mock.call(-1, attributes=None),
        ]
        # Create the metric and set value to 1
        self.stats.incr(name)

        # Decrement value to 0
        self.stats.decr(name)

        self.map[full_name(name)].add.assert_has_calls(expected_calls)
        assert self.map[full_name(name)].add.call_count == len(expected_calls)

    @mock.patch("random.random", side_effect=[0.1, 0.9])
    def test_decr_with_rate_limit_works(self, mock_random, name):
        expected_calls = [
            mock.call(1, attributes=None),
            mock.call(-1, attributes=None),
        ]
        # Create the metric and set value to 1
        self.stats.incr(name)

        # Decrement the counter to 0
        self.stats.decr(name, rate=0.5)
        # This one should not decrement because random() will return a value higher than `rate`
        self.stats.decr(name, rate=0.5)
        # This one should raise an exception for a negative `rate` value
        with pytest.raises(ValueError, match=RATE_MUST_BE_POSITIVE_MSG):
            self.stats.decr(name, rate=-0.5)

        assert mock_random.call_count == 2
        # add() is called once in the initial stats.incr and once for the decr that passed the rate check.
        self.map[full_name(name)].add.assert_has_calls(expected_calls)
        assert self.map[full_name(name)].add.call_count == 2

    def test_gauge_new_metric(self, name):
        self.stats.gauge(name, value=1)

        self.meter.get_meter().create_gauge.assert_called_once_with(name=full_name(name))
        assert self.map[full_name(name)].value == 1

    def test_gauge_new_metric_with_tags(self, name):
        tags = {"hello": "world"}
        key = _generate_key_name(full_name(name), tags)

        self.stats.gauge(name, value=1, tags=tags)

        self.meter.get_meter().create_gauge.assert_called_once_with(name=full_name(name))
        assert self.map[key].attributes == tags

    def test_gauge_existing_metric(self, name):
        self.stats.gauge(name, value=1)
        self.stats.gauge(name, value=2)

        self.meter.get_meter().create_gauge.assert_called_once_with(name=full_name(name))
        assert self.map[full_name(name)].value == 2

    def test_gauge_existing_metric_with_delta(self, name):
        self.stats.gauge(name, value=1)
        self.stats.gauge(name, value=2, delta=True)

        self.meter.get_meter().create_gauge.assert_called_once_with(name=full_name(name))
        assert self.map[full_name(name)].value == 3

    @mock.patch("random.random", side_effect=[0.1, 0.9])
    @mock.patch.object(MetricsMap, "set_gauge_value")
    def test_gauge_with_rate_limit_works(self, mock_set_value, mock_random, name):
        # Create the gauge and set the value to 1
        self.stats.gauge(name, value=1, rate=0.5)
        # This one should not increment because random() will return a value higher than `rate`
        self.stats.gauge(name, value=1, rate=0.5)

        with pytest.raises(ValueError, match=RATE_MUST_BE_POSITIVE_MSG):
            self.stats.gauge(name, value=1, rate=-0.5)

        assert mock_random.call_count == 2
        assert mock_set_value.call_count == 1

    def test_gauge_value_is_correct(self, name):
        self.stats.gauge(name, value=1)

        assert self.map[full_name(name)].value == 1

    def test_timing_new_metric(self, name):
        import datetime

        self.stats.timing(name, dt=datetime.timedelta(seconds=123))

        self.meter.get_meter().create_histogram.assert_called_once_with(name=full_name(name), unit="ms")
        self.meter.get_meter().create_histogram.return_value.record.assert_called_once_with(
            123000.0, attributes=None
        )

    def test_timing_new_metric_with_tags(self, name):
        tags = {"hello": "world"}

        self.stats.timing(name, dt=1, tags=tags)

        self.meter.get_meter().create_histogram.assert_called_once_with(name=full_name(name), unit="ms")
        self.meter.get_meter().create_histogram.return_value.record.assert_called_once_with(
            1.0, attributes=tags
        )

    def test_timing_existing_metric(self, name):
        self.stats.timing(name, dt=1)
        self.stats.timing(name, dt=2)

        # histogram created only once, but both observations are recorded
        self.meter.get_meter().create_histogram.assert_called_once_with(name=full_name(name), unit="ms")
        assert self.meter.get_meter().create_histogram.return_value.record.call_count == 2

    # For the four test_timer_foo tests below:
    #   time.perf_count() is called once to get the starting timestamp and again
    #   to get the end timestamp.  timer() should return the difference as a float.

    @mock.patch.object(time, "perf_counter", side_effect=[0.0, 3.14])
    def test_timer_with_name_returns_float_and_stores_value(self, mock_time, name):
        with self.stats.timer(name) as timer:
            pass

        assert isinstance(timer.duration, float)
        expected_duration = 3140.0
        assert timer.duration == expected_duration
        assert mock_time.call_count == 2
        self.meter.get_meter().create_histogram.assert_called_once_with(name=full_name(name), unit="ms")

    @mock.patch.object(time, "perf_counter", side_effect=[0.0, 3.14])
    def test_timer_no_name_returns_float_but_does_not_store_value(self, mock_time, name):
        with self.stats.timer() as timer:
            pass

        assert hasattr(timer, "duration")
        assert isinstance(timer.duration, float)
        expected_duration = 3140.0
        assert timer.duration == expected_duration
        assert mock_time.call_count == 2
        self.meter.get_meter().create_histogram.assert_not_called()

    @mock.patch.object(time, "perf_counter", side_effect=[0.0, 3.14])
    def test_timer_start_and_stop_manually_send_false(self, mock_time, name):
        timer = self.stats.timer(name)
        timer.start()
        # Perform some task
        timer.stop(send=False)

        assert isinstance(timer.duration, float)
        expected_value = 3140.0
        assert timer.duration == expected_value
        assert mock_time.call_count == 2
        self.meter.get_meter().create_histogram.assert_not_called()

    @mock.patch.object(time, "perf_counter", side_effect=[0.0, 3.14])
    def test_timer_start_and_stop_manually_send_true(self, mock_time, name):
        timer = self.stats.timer(name)
        timer.start()
        # Perform some task
        timer.stop(send=True)

        assert isinstance(timer.duration, float)
        expected_value = 3140.0
        assert timer.duration == expected_value
        assert mock_time.call_count == 2
        self.meter.get_meter().create_histogram.assert_called_once_with(name=full_name(name), unit="ms")

    @pytest.mark.parametrize(
        (
            "provided_env_vars",
            "airflow_conf_host",
            "airflow_conf_port",
            "expected_endpoint",
            "expected_exporter_module",
        ),
        [
            pytest.param(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:1234",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                },
                "breeze-otel-collector",
                "4318",
                "localhost:1234",
                "grpc",
                id="env_vars_with_grpc",
            ),
            pytest.param(
                {
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                },
                "breeze-otel-collector",
                "4318",
                "http://breeze-otel-collector:4318/v1/metrics",
                "http",
                id="protocol_is_ignored_if_no_env_endpoint",
            ),
            pytest.param(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:1234",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                },
                "breeze-otel-collector",
                "4318",
                "http://localhost:1234/v1/metrics",
                "http",
                id="for_http_with_env_vars_otel_builds_full_url",
            ),
            pytest.param(
                {},
                "breeze-otel-collector",
                "4318",
                "http://breeze-otel-collector:4318/v1/metrics",
                "http",
                id="use_airflow_config",
            ),
            pytest.param(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:1234",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                },
                None,
                None,
                "http://localhost:1234/v1/metrics",
                "http",
                id="only_env_vars",
            ),
            pytest.param(
                {
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:1234",
                    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://localhost:2222",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "grpc",
                },
                None,
                None,
                "localhost:2222",
                "grpc",
                id="type_specific_vars_take_precedence",
            ),
            pytest.param(
                {},
                "::1",
                "4318",
                "http://[::1]:4318/v1/metrics",
                "http",
                id="airflow_config_ipv6_loopback_is_bracketed",
            ),
            pytest.param(
                {},
                "2001:db8::1",
                "4318",
                "http://[2001:db8::1]:4318/v1/metrics",
                "http",
                id="airflow_config_ipv6_literal_is_bracketed",
            ),
            pytest.param(
                {},
                "[::1]",
                "4318",
                "http://[::1]:4318/v1/metrics",
                "http",
                id="airflow_config_already_bracketed_ipv6_is_preserved",
            ),
            pytest.param(
                {},
                "10.0.0.1",
                "4318",
                "http://10.0.0.1:4318/v1/metrics",
                "http",
                id="airflow_config_ipv4_literal_passes_through_unchanged",
            ),
        ],
    )
    def test_config_priorities(
        self,
        provided_env_vars,
        airflow_conf_host,
        airflow_conf_port,
        expected_endpoint,
        expected_exporter_module,
    ):
        with env_vars(provided_env_vars):
            otel_env_config = load_metrics_env_config()

            otel_metric_exporter = get_otel_data_exporter(
                otel_env_config=otel_env_config,
                host=airflow_conf_host,
                port=airflow_conf_port,
            )

            assert otel_metric_exporter._endpoint == expected_endpoint

            assert (
                otel_metric_exporter.__class__.__module__
                == f"opentelemetry.exporter.otlp.proto.{expected_exporter_module}.metric_exporter"
            )

    @mock.patch("airflow_shared.observability.metrics.otel_logger.metrics")
    @mock.patch("airflow_shared.observability.metrics.otel_logger.MeterProvider")
    def test_get_otel_logger_uses_exponential_histogram_view(self, mock_provider, mock_metrics):
        get_otel_logger(host="localhost", port=4318)

        call_kwargs = mock_provider.call_args.kwargs
        views = call_kwargs["views"]
        assert len(views) == 1
        view = views[0]
        assert isinstance(view, View)
        assert isinstance(view._aggregation, ExponentialBucketHistogramAggregation)

    def test_declaratively_configured_provider_is_not_replaced(self, reset_meter_provider):
        """A MeterProvider built from OTEL_CONFIG_FILE must survive get_otel_logger().

        The declarative configuration spec makes that file the sole source of SDK
        construction, so replacing its provider silently drops the deployment's views.
        See https://github.com/apache/airflow/issues/64690 for why the provider is
        otherwise force-replaced.
        """
        declarative_view = View(
            instrument_name="*_duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=(0.5, 1, 2, 4, 8)),
        )
        configured_provider = SDKMeterProvider(views=[declarative_view], shutdown_on_exit=False)
        metrics.set_meter_provider(configured_provider)

        with env_vars({"OTEL_CONFIG_FILE": "/tmp/otel-config.yaml"}):
            logger = get_otel_logger(host="localhost", port=4318)

        assert logger.otel is configured_provider
        assert metrics.get_meter_provider() is configured_provider
        assert list(configured_provider._sdk_config.views) == [declarative_view]

    def test_provider_is_replaced_without_declarative_config(self, reset_meter_provider):
        """Without OTEL_CONFIG_FILE, Airflow still installs its own provider."""
        pre_existing = SDKMeterProvider(shutdown_on_exit=False)
        metrics.set_meter_provider(pre_existing)

        logger = get_otel_logger(host="localhost", port=4318)

        assert logger.otel is not pre_existing

    def test_atexit_flush_on_process_exit(self):
        """
        Run a process that initializes a logger, creates a stat and then exits.

        The logger initialization registers an atexit hook.
        Test that the hook runs and flushes the created stat at shutdown.
        """
        function_call_str = (
            "from airflow_shared.observability.metrics.otel_logger import get_otel_logger; "
            "logger = get_otel_logger(debug=True); "
            "logger.incr('my_test_stat')"
        )

        proc = subprocess.run(
            [sys.executable, "-c", function_call_str],
            check=False,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=20,
        )

        assert proc.returncode == 0, f"Process failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

        assert "my_test_stat" in proc.stdout, (
            "Expected the metric name to be present in the stdout but it wasn't.\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )

    def test_forked_child_exports_its_own_metrics(self):
        """Test that a forked child builds its own live pipeline instead of adopting the parent's.

        Guards https://github.com/apache/airflow/issues/64690: the OTel SDK's Once() guard on
        set_meter_provider() survives fork, so without the reset the child silently keeps the
        parent's provider, whose reader thread it does not own. Reusing a provider within one
        process must not extend to one inherited across a fork.
        """
        proc = run_in_subprocess(FORK_PROGRAM)

        assert proc.returncode == 0, f"Process failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

        context = f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        assert "CHILD_BUILT_OWN_PROVIDER=True" in proc.stdout, (
            f"The child adopted the provider it inherited from the parent.\n{context}"
        )
        assert "CHILD_HAS_LIVE_READER=True" in proc.stdout, (
            f"The child's own provider has no live exporter thread.\n{context}"
        )
        assert "post_fork_stat" in proc.stdout, (
            f"Expected 'post_fork_stat' in stdout but it wasn't found.\n{context}"
        )


class TestOtelProviderIsProcessScoped:
    """The process gets one MeterProvider however many callers ask for a logger."""

    def test_repeated_calls_reuse_one_provider(self, reset_meter_provider):
        """Test that calling get_otel_logger() again reuses the provider instead of leaking one."""
        first = get_otel_logger(host="localhost", port=4318)
        readers_after_first = count_metric_reader_threads()

        second = get_otel_logger(host="localhost", port=4318)

        assert second.otel is first.otel
        assert count_metric_reader_threads() == readers_after_first

    def test_a_second_module_copy_reuses_one_provider(self, reset_meter_provider):
        """Test that an independently imported copy of this module shares the same provider."""
        second_copy = load_independent_module_copy()
        assert second_copy is not otel_logger_module

        first = get_otel_logger(host="localhost", port=4318)
        readers_after_first = count_metric_reader_threads()

        second = second_copy.get_otel_logger(host="localhost", port=4318)

        assert second.otel is first.otel
        assert count_metric_reader_threads() == readers_after_first

    @pytest.mark.parametrize(
        ("attribute", "first_value", "second_value"),
        [
            pytest.param("prefix", "alpha", "beta", id="prefix"),
            pytest.param("statsd_influxdb_enabled", True, False, id="statsd_influxdb_enabled"),
        ],
    )
    def test_sharing_a_provider_keeps_per_caller_configuration(
        self, attribute, first_value, second_value, reset_meter_provider
    ):
        """Test that callers sharing one provider still get their own logger configuration."""
        first = get_otel_logger(host="localhost", port=4318, **{attribute: first_value})
        second = get_otel_logger(host="localhost", port=4318, **{attribute: second_value})

        assert first.otel is second.otel
        assert getattr(first, attribute) == first_value
        assert getattr(second, attribute) == second_value

    def test_a_provider_built_by_another_process_is_not_reused(self, reset_meter_provider):
        """Test that a provider inherited from another process is replaced, not adopted."""
        inherited = SDKMeterProvider(shutdown_on_exit=False)
        setattr(inherited, _OWNER_PID_ATTR, os.getpid() + 1)
        metrics.set_meter_provider(inherited)

        logger = get_otel_logger(host="localhost", port=4318)

        assert logger.otel is not inherited

    def test_both_module_copies_still_export_their_metrics(self):
        """Test that sharing one provider does not stop either module copy emitting metrics."""
        proc = run_in_subprocess(TWO_MODULE_COPIES_PROGRAM)

        assert proc.returncode == 0, f"Process failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

        context = f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        assert "COPIES_SHARE_PROVIDER=True" in proc.stdout, (
            f"The two module copies each built their own provider.\n{context}"
        )
        assert "copyone.from_first_copy" in proc.stdout, (
            f"The first module copy's metric was not exported.\n{context}"
        )
        assert "copytwo.from_second_copy" in proc.stdout, (
            f"The second module copy's metric was not exported.\n{context}"
        )


def count_metric_reader_threads() -> int:
    """Count the live OTel exporter threads, one of which every MeterProvider starts."""
    return len([t for t in threading.enumerate() if "MetricReader" in t.name and t.is_alive()])


def load_independent_module_copy():
    """
    Load a second, independent copy of otel_logger, as the two ``_shared`` symlinks do.

    ``shared/observability`` is symlinked into both ``airflow/_shared`` and
    ``airflow/sdk/_shared``, so the same file is executed twice under two names and each copy gets
    its own module globals. The name below keeps the package prefix so the module's relative
    imports still resolve.
    """
    spec = importlib.util.spec_from_file_location(
        "airflow_shared.observability.metrics._otel_logger_second_copy",
        otel_logger_module.__file__,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mock_service_run():
    logger = get_otel_logger(debug=True)
    logger.incr("my_test_stat")


def run_in_subprocess(program: str) -> subprocess.CompletedProcess:
    """Run a self-contained program in a fresh interpreter and capture its output."""
    return subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )


# These run in a fresh interpreter because both need a process whose global MeterProvider starts
# out unset. They import only the installed package, so they do not depend on this test module
# being importable by name from the subprocess's working directory.

FORK_PROGRAM = """
import os
import sys
import threading

from airflow_shared.observability.metrics.otel_logger import get_otel_logger

parent_logger = get_otel_logger(debug=True)
parent_logger.incr("pre_fork_stat")

if os.fork() == 0:
    child_logger = get_otel_logger(debug=True)
    child_logger.incr("post_fork_stat")
    live_readers = [t for t in threading.enumerate() if "MetricReader" in t.name and t.is_alive()]
    print("CHILD_BUILT_OWN_PROVIDER=%s" % (child_logger.otel is not parent_logger.otel))
    print("CHILD_HAS_LIVE_READER=%s" % (len(live_readers) > 0))
    # os._exit skips the atexit flush, so publish the child's metrics explicitly.
    child_logger.otel.force_flush()
    sys.stdout.flush()
    os._exit(0)

os.wait()
"""

TWO_MODULE_COPIES_PROGRAM = """
import importlib.util

from airflow_shared.observability.metrics import otel_logger as first_copy

spec = importlib.util.spec_from_file_location(
    "airflow_shared.observability.metrics._otel_logger_second_copy", first_copy.__file__
)
second_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(second_copy)

first_logger = first_copy.get_otel_logger(debug=True, prefix="copyone")
second_logger = second_copy.get_otel_logger(debug=True, prefix="copytwo")

print("COPIES_SHARE_PROVIDER=%s" % (first_logger.otel is second_logger.otel))

first_logger.incr("from_first_copy")
second_logger.incr("from_second_copy")

# Flush both explicitly so that what was exported is asserted independently of whether the two
# copies ended up sharing one provider.
first_logger.otel.force_flush()
second_logger.otel.force_flush()
"""
