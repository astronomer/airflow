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

import copy
from datetime import timedelta
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult

# LLMRetryPolicy depends on the RetryPolicy ABC introduced in Airflow 3.3 (AIP-105).
# Skip the entire test module on older Airflow versions tested in compat CI.
pytest.importorskip("airflow.sdk.definitions.retry_policy", reason="RetryPolicy requires Airflow 3.3+")

from airflow.providers.common.ai.policies.retry import (
    DEFAULT_INSTRUCTIONS,
    DEFAULT_RETRY_DELAYS,
    ERROR_CATEGORIES,
    ErrorClassification,
    LLMRetryPolicy,
    redact_registered_secrets,
)
from airflow.sdk._shared.secrets_masker import reset_secrets_masker
from airflow.sdk.definitions.retry_policy import RetryAction, RetryRule
from airflow.sdk.log import mask_secret


def _make_mock_agent(category, reasoning="test"):
    """Create a mock agent that returns a canned ErrorClassification."""
    mock_result = MagicMock(spec=AgentRunResult)
    mock_result.output = ErrorClassification(category=category, reasoning=reasoning)
    mock_agent = MagicMock(spec=Agent)
    mock_agent.run_sync.return_value = mock_result
    return mock_agent


@pytest.mark.enable_redact
def test_redact_registered_secrets_masks_only_registered_values():
    """Docs tell Dag authors to import and wrap this, so both the name and its narrow scope are contracts."""
    reset_secrets_masker()
    mask_secret("super-secret-conn-password")

    assert (
        redact_registered_secrets("contact user@example.com with super-secret-conn-password")
        == "contact user@example.com with ***"
    )


class TestErrorClassificationSchema:
    """The category set is a closed contract, not a hint in the prompt."""

    def test_category_names_are_pinned(self):
        """Spelled out here on purpose.

        ``ERROR_CATEGORIES`` is both the schema and the gate ``retry_delays`` validates
        against, so a test that derives its expectations from it cannot catch a rename or
        a dropped member. The prompt has to move with them or the model is offered names
        the schema rejects.
        """
        expected = ("rate_limit", "auth", "network", "data", "resource", "transient", "permanent")

        assert expected == ERROR_CATEGORIES
        assert get_args(ErrorClassification.model_fields["category"].annotation) == expected
        for category in expected:
            assert f"- {category}:" in DEFAULT_INSTRUCTIONS

    @pytest.mark.parametrize("category", ERROR_CATEGORIES)
    def test_every_documented_category_validates(self, category):
        assert ErrorClassification(category=category, reasoning="x").category == category

    @pytest.mark.parametrize(
        "category",
        ["rate-limit", "RATE_LIMIT", "Rate limit exceeded, should retry after a delay", ""],
    )
    def test_category_outside_the_set_is_rejected(self, category):
        """A near-miss spelling or a sentence must not reach the retry decision."""
        with pytest.raises(ValidationError):
            ErrorClassification(category=category, reasoning="x")

    def test_default_retry_delays_cannot_be_mutated(self):
        """The default table is shared by every policy instance, so it must be read-only."""
        with pytest.raises(TypeError):
            DEFAULT_RETRY_DELAYS["auth"] = timedelta(seconds=1)  # type: ignore[index]

    def test_default_retry_delays_only_names_known_categories(self):
        assert set(DEFAULT_RETRY_DELAYS) <= set(ERROR_CATEGORIES)


class TestLLMClassifyDecisions:
    """Test that _classify maps LLM classification to correct RetryDecisions."""

    @pytest.mark.parametrize(
        ("category", "expected_action", "expected_delay"),
        [
            pytest.param("rate_limit", RetryAction.RETRY, timedelta(seconds=60), id="rate_limit"),
            pytest.param("network", RetryAction.RETRY, timedelta(seconds=10), id="network"),
            pytest.param("transient", RetryAction.RETRY, timedelta(seconds=30), id="transient"),
            pytest.param("auth", RetryAction.FAIL, None, id="auth"),
            pytest.param("data", RetryAction.FAIL, None, id="data"),
            pytest.param("resource", RetryAction.FAIL, None, id="resource"),
            pytest.param("permanent", RetryAction.FAIL, None, id="permanent"),
        ],
    )
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_default_table_covers_every_category(
        self, mock_hook_cls, category, expected_action, expected_delay
    ):
        """The retry/fail split and the delays are the documented defaults, derived in-process."""
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent(category)
        policy = LLMRetryPolicy(llm_conn_id="test")

        decision = policy.evaluate(RuntimeError("boom"), try_number=1, max_tries=3)

        assert decision.action == expected_action
        assert decision.retry_delay == expected_delay

    @pytest.mark.parametrize(
        ("category", "reasoning", "expected"),
        [
            pytest.param("auth", "API key expired", "auth: API key expired", id="fail-branch"),
            # RETRY is the branch whose reason is persisted to the task instance's
            # retry_reason, so it is the one a Dag author actually reads.
            pytest.param("rate_limit", "429 from the API", "rate_limit: 429 from the API", id="retry-branch"),
        ],
    )
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_reason_carries_category_and_reasoning(self, mock_hook_cls, category, reasoning, expected):
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent(category, reasoning)
        policy = LLMRetryPolicy(llm_conn_id="test")

        decision = policy.evaluate(RuntimeError("boom"), try_number=1, max_tries=3)

        assert decision.reason == expected

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_retry_delays_replaces_the_default_table(self, mock_hook_cls):
        """Passing retry_delays replaces the defaults, so an omitted category now fails."""
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("rate_limit")
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays={"auth": timedelta(seconds=5)})

        decision = policy.evaluate(RuntimeError("429"), try_number=1, max_tries=3)

        assert decision.action == RetryAction.FAIL

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_retry_delays_can_retry_a_default_fail_category(self, mock_hook_cls):
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("auth")
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays={"auth": timedelta(seconds=5)})

        decision = policy.evaluate(PermissionError("expired token"), try_number=1, max_tries=3)

        assert decision.action == RetryAction.RETRY
        assert decision.retry_delay == timedelta(seconds=5)

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_none_delay_leaves_the_task_backoff_in_charge(self, mock_hook_cls):
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("transient")
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays={"transient": None})

        decision = policy.evaluate(RuntimeError("glitch"), try_number=1, max_tries=3)

        assert decision.action == RetryAction.RETRY
        assert decision.retry_delay is None

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_empty_retry_delays_fails_every_category(self, mock_hook_cls):
        """An empty mapping is a real choice -- classify and always fail -- not "use defaults"."""
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("rate_limit")
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays={})

        decision = policy.evaluate(RuntimeError("429"), try_number=1, max_tries=3)

        assert decision.action == RetryAction.FAIL

    def test_unknown_category_in_retry_delays_raises(self):
        with pytest.raises(ValueError, match="cannot return: \\['flaky', 'rate-limit'\\]"):
            LLMRetryPolicy(
                llm_conn_id="test",
                retry_delays={"rate-limit": timedelta(seconds=1), "flaky": None},
            )

    def test_negative_delay_in_retry_delays_raises(self):
        with pytest.raises(ValueError, match="must not be negative, got negative delays for \\['auth'\\]"):
            LLMRetryPolicy(llm_conn_id="test", retry_delays={"auth": timedelta(seconds=-1)})

    def test_int_seconds_in_retry_delays_raises(self):
        """Int seconds was the shape of the removed ``suggested_delay_seconds`` field."""
        with pytest.raises(ValueError, match="must be timedelta or None, got \\['rate_limit=60'\\]"):
            LLMRetryPolicy(llm_conn_id="test", retry_delays={"rate_limit": 60})

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_zero_delay_retries_without_waiting(self, mock_hook_cls):
        """timedelta(0) is an override to retry at once, distinct from None."""
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("transient")
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays={"transient": timedelta(0)})

        decision = policy.evaluate(RuntimeError("glitch"), try_number=1, max_tries=3)

        assert decision.action == RetryAction.RETRY
        assert decision.retry_delay == timedelta(0)

    @pytest.mark.parametrize(
        "retry_delays",
        [
            pytest.param(None, id="default-table"),
            pytest.param({"rate_limit": timedelta(seconds=1)}, id="caller-table"),
        ],
    )
    def test_policy_can_be_deep_copied(self, retry_delays):
        """``TaskGroup(default_args={"retry_policy": ...})`` deep-copies the policy.

        The default table is a mappingproxy, which cannot be pickled, so holding it by
        reference would make the documented configuration the one that fails at Dag parse.
        """
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays=retry_delays)

        assert copy.deepcopy(policy).retry_delays == policy.retry_delays

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_caller_mapping_is_copied(self, mock_hook_cls):
        """Mutating the caller's mapping after construction must not change the policy."""
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("rate_limit")
        delays = {"rate_limit": timedelta(seconds=7)}
        policy = LLMRetryPolicy(llm_conn_id="test", retry_delays=delays)
        delays["rate_limit"] = timedelta(seconds=999)

        decision = policy.evaluate(RuntimeError("429"), try_number=1, max_tries=3)

        assert decision.retry_delay == timedelta(seconds=7)

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_prompt_includes_exception_type_and_message(self, mock_hook_cls):
        mock_agent = _make_mock_agent("data")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test")
        policy.evaluate(ValueError("bad column type"), try_number=2, max_tries=5)

        prompt = mock_agent.run_sync.call_args[0][0]
        assert "ValueError: bad column type" in prompt
        assert "attempt 2 of 5" in prompt

    @pytest.mark.enable_redact
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_prompt_redacts_known_secrets(self, mock_hook_cls):
        reset_secrets_masker()
        secret_value = "super-secret-conn-password"
        mask_secret(secret_value)

        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test")
        policy.evaluate(
            ConnectionError(f"could not authenticate with password {secret_value}"),
            try_number=1,
            max_tries=3,
        )

        prompt = mock_agent.run_sync.call_args[0][0]
        assert secret_value not in prompt
        assert prompt == (
            "Classify this error from a data pipeline task (attempt 1 of 3):\n\n"
            "ConnectionError: could not authenticate with password ***"
        )

    @pytest.mark.enable_redact
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_prompt_keeps_raw_message_when_redaction_disabled(self, mock_hook_cls):
        reset_secrets_masker()
        secret_value = "super-secret-conn-password"
        mask_secret(secret_value)

        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test", redact_exception=False)
        policy.evaluate(
            ConnectionError(f"could not authenticate with password {secret_value}"),
            try_number=1,
            max_tries=3,
        )

        prompt = mock_agent.run_sync.call_args[0][0]
        assert secret_value in prompt

    @pytest.mark.enable_redact
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_explicit_redactor_none_still_applies_default_masking(self, mock_hook_cls):
        """redactor=None means "use the default masker" -- the same as omitting it."""
        reset_secrets_masker()
        secret_value = "super-secret-conn-password"
        mask_secret(secret_value)

        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test", redactor=None)
        policy.evaluate(
            ConnectionError(f"could not authenticate with password {secret_value}"),
            try_number=1,
            max_tries=3,
        )

        prompt = mock_agent.run_sync.call_args[0][0]
        assert secret_value not in prompt
        assert "***" in prompt

    def test_redact_exception_false_with_explicit_redactor_raises(self):
        with pytest.raises(ValueError, match="redactor must not be set when redact_exception=False"):
            LLMRetryPolicy(llm_conn_id="test", redact_exception=False, redactor=lambda message: message)

    @pytest.mark.enable_redact
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_custom_redactor_replaces_masker_instead_of_stacking(self, mock_hook_cls):
        """A custom redactor replaces the secrets masker entirely -- it is not applied on top."""
        reset_secrets_masker()
        secret_value = "super-secret-conn-password"
        mask_secret(secret_value)

        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test", redactor=lambda s: s.replace("authenticate", "REDACTED"))
        policy.evaluate(
            ConnectionError(f"could not authenticate with password {secret_value}"),
            try_number=1,
            max_tries=3,
        )

        prompt = mock_agent.run_sync.call_args[0][0]
        # The registered secret is untouched by the masker...
        assert secret_value in prompt
        # ...but the custom redactor's own transformation did apply.
        assert "REDACTED" in prompt

    @pytest.mark.parametrize(
        ("max_exception_length", "message_length", "expect_truncated"),
        [
            pytest.param(4096, 4096, False, id="default-limit-exact-fit"),
            pytest.param(4096, 5000, True, id="default-limit-exceeded"),
            pytest.param(10, 20, True, id="custom-limit-exceeded"),
            pytest.param(10, 5, False, id="custom-limit-under"),
        ],
    )
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_message_truncated_when_over_max_exception_length(
        self, mock_hook_cls, max_exception_length, message_length, expect_truncated
    ):
        mock_agent = _make_mock_agent("data")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(
            llm_conn_id="test", redact_exception=False, max_exception_length=max_exception_length
        )
        policy.evaluate(ValueError("x" * message_length), try_number=1, max_tries=3)

        prompt = mock_agent.run_sync.call_args[0][0]
        assert ("... (truncated)" in prompt) is expect_truncated
        if expect_truncated:
            assert f"{'x' * max_exception_length}... (truncated)" in prompt
        else:
            assert "x" * message_length in prompt

    @pytest.mark.enable_redact
    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_truncation_happens_after_redaction(self, mock_hook_cls):
        """Redact-then-truncate must not equal truncate-then-redact for this input.

        The secret sits right at the truncation boundary: truncating first would slice
        it in half so the masker could no longer recognize and mask it.
        """
        reset_secrets_masker()
        secret_value = "super-secret-conn-password"
        mask_secret(secret_value)
        max_exception_length = 20
        # Padding places the secret so it straddles the truncation boundary.
        padding = "a" * (max_exception_length - 5)
        message = f"{padding}{secret_value}"

        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test", max_exception_length=max_exception_length)
        policy.evaluate(ConnectionError(message), try_number=1, max_tries=3)

        prompt = mock_agent.run_sync.call_args[0][0]
        assert secret_value not in prompt
        assert "***" in prompt

    @pytest.mark.parametrize("max_exception_length", [0, -1, -100])
    def test_non_positive_max_exception_length_raises(self, max_exception_length):
        with pytest.raises(ValueError, match="max_exception_length must be a positive integer"):
            LLMRetryPolicy(llm_conn_id="test", max_exception_length=max_exception_length)

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_custom_instructions_forwarded_to_agent(self, mock_hook_cls):
        mock_hook_cls.return_value.create_agent.return_value = _make_mock_agent("permanent")

        policy = LLMRetryPolicy(llm_conn_id="test", instructions="My custom prompt")
        policy.evaluate(ValueError("x"), try_number=1, max_tries=3)

        mock_hook_cls.return_value.create_agent.assert_called_once_with(
            output_type=ErrorClassification,
            instructions="My custom prompt",
        )

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_timeout_passed_via_model_settings(self, mock_hook_cls):
        mock_agent = _make_mock_agent("auth")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(llm_conn_id="test", timeout=15.0)
        policy.evaluate(ValueError("x"), try_number=1, max_tries=3)

        model_settings = mock_agent.run_sync.call_args.kwargs["model_settings"]
        assert model_settings["timeout"] == 15.0


class TestLLMFallbackBehaviour:
    """Test fallback when the LLM call itself fails."""

    def test_falls_back_to_rules_when_connection_missing(self):
        policy = LLMRetryPolicy(
            llm_conn_id="nonexistent",
            fallback_rules=[
                RetryRule(
                    exception=ConnectionError, action=RetryAction.RETRY, retry_delay=timedelta(seconds=10)
                ),
                RetryRule(exception=PermissionError, action=RetryAction.FAIL, reason="auth fallback"),
            ],
        )
        d = policy.evaluate(ConnectionError("refused"), try_number=1, max_tries=3)
        assert d.action == RetryAction.RETRY
        assert d.retry_delay == timedelta(seconds=10)

        d = policy.evaluate(PermissionError("denied"), try_number=1, max_tries=3)
        assert d.action == RetryAction.FAIL

    def test_falls_back_to_default_when_no_rules(self):
        policy = LLMRetryPolicy(llm_conn_id="nonexistent")
        d = policy.evaluate(ValueError("bad"), try_number=1, max_tries=3)
        assert d.action == RetryAction.DEFAULT

    def test_fallback_rules_no_match_returns_default(self):
        """When fallback rules exist but none match, DEFAULT is returned."""
        policy = LLMRetryPolicy(
            llm_conn_id="nonexistent",
            fallback_rules=[
                RetryRule(exception=PermissionError, action=RetryAction.FAIL),
            ],
        )
        # ValueError doesn't match the PermissionError rule
        d = policy.evaluate(ValueError("bad"), try_number=1, max_tries=3)
        assert d.action == RetryAction.DEFAULT

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_agent_run_sync_failure_triggers_fallback(self, mock_hook_cls):
        """Failure during run_sync (not hook creation) still triggers fallback."""
        mock_agent = MagicMock()
        mock_agent.run_sync.side_effect = RuntimeError("network error mid-call")
        mock_hook_cls.return_value.create_agent.return_value = mock_agent

        policy = LLMRetryPolicy(
            llm_conn_id="test",
            fallback_rules=[RetryRule(exception=ValueError, action=RetryAction.FAIL, reason="fallback")],
        )
        d = policy.evaluate(ValueError("x"), try_number=1, max_tries=3)
        assert d.action == RetryAction.FAIL
        assert d.reason == "fallback"

    @patch("airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook", autospec=True)
    def test_hook_creation_failure_triggers_fallback(self, mock_hook_cls):
        """Failure during hook.create_agent still triggers fallback."""
        mock_hook_cls.return_value.create_agent.side_effect = RuntimeError("unexpected")

        policy = LLMRetryPolicy(
            llm_conn_id="test",
            fallback_rules=[RetryRule(exception=ValueError, action=RetryAction.FAIL, reason="caught")],
        )
        d = policy.evaluate(ValueError("x"), try_number=1, max_tries=3)
        assert d.action == RetryAction.FAIL
