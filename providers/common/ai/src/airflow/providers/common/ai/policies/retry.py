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
LLM-powered retry policy using pydantic-ai for error classification.

Requires Airflow 3.3+ (RetryPolicy was added in AIP-105).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, cast, get_args

from pydantic import BaseModel

from airflow.providers.common.compat.sdk import redact

try:
    from airflow.sdk.definitions.retry_policy import (
        ExceptionRetryPolicy,
        RetryDecision,
        RetryPolicy,
    )
except ImportError:
    raise ImportError(
        "LLMRetryPolicy requires Airflow 3.3+ which includes RetryPolicy support. "
        "Please upgrade apache-airflow-core."
    ) from None

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from airflow.sdk.definitions.context import Context
    from airflow.sdk.definitions.retry_policy import RetryRule

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_RETRY_DELAYS",
    "ERROR_CATEGORIES",
    "ErrorCategory",
    "ErrorClassification",
    "LLMRetryPolicy",
    "redact_registered_secrets",
]

ErrorCategory = Literal[
    "rate_limit",
    "auth",
    "network",
    "data",
    "resource",
    "transient",
    "permanent",
]
"""The categories the classifier is allowed to return."""

ERROR_CATEGORIES: tuple[ErrorCategory, ...] = get_args(ErrorCategory)

DEFAULT_RETRY_DELAYS: Mapping[ErrorCategory, timedelta | None] = MappingProxyType(
    {
        "rate_limit": timedelta(seconds=60),
        "network": timedelta(seconds=10),
        "transient": timedelta(seconds=30),
    }
)
"""Categories that are retried, and how long to wait first.

A category absent from this mapping fails the task. A ``None`` value retries
without overriding the task's own ``retry_delay`` and backoff.
"""

DEFAULT_INSTRUCTIONS = (
    "You are an error classifier for a data pipeline system. "
    "Given an error message from a failed task, classify it into one of these categories:\n\n"
    "- rate_limit: API throttling or quota exceeded.\n"
    "- auth: Credentials invalid, expired, or missing permissions.\n"
    "- network: Transient connectivity issue.\n"
    "- data: Schema validation, type mismatch, or bad input data.\n"
    "- resource: Resource not found or unavailable (e.g., missing table, bucket).\n"
    "- transient: Temporary issue likely to resolve on its own.\n"
    "- permanent: Problem that won't resolve without code or config changes.\n\n"
    "Pick the single best fit and explain the choice in one sentence."
)


class ErrorClassification(BaseModel):
    """Structured LLM output for error classification."""

    category: ErrorCategory
    """Which kind of failure this is."""
    reasoning: str
    """Brief explanation of the classification decision."""


def redact_registered_secrets(message: str) -> str:
    """Mask values registered via ``mask_secret()``; the default ``redactor`` for :class:`LLMRetryPolicy`."""
    # redact() is typed for arbitrary containers; a str in always yields a str out.
    return cast("str", redact(message))


class LLMRetryPolicy(RetryPolicy):
    """
    Retry policy that uses an LLM to classify errors and decide retry behaviour.

    Uses :class:`~airflow.providers.common.ai.hooks.pydantic_ai.PydanticAIHook`
    to call any configured LLM provider (OpenAI, Anthropic, Bedrock, Vertex,
    Ollama, etc.) for error classification with structured output.

    The model's only job is to name the failure: it picks one of
    :data:`ERROR_CATEGORIES` and explains the choice. Whether that category is
    retried, and after how long, comes from ``retry_delays`` in this process.

    When the LLM call itself fails, the policy falls back to ``fallback_rules``
    (if provided) or returns DEFAULT to use the task's standard retry logic.

    :param llm_conn_id: Airflow connection ID for the LLM provider.
    :param model_id: Model identifier override (e.g. ``"openai:gpt-4o-mini"``
        for cost efficiency). If not set, uses the model from the connection.
    :param instructions: Custom system prompt for classification.
        Defaults to a general-purpose error classifier. Instructions can
        change how errors are sorted into :data:`ERROR_CATEGORIES`, but not
        what the categories are -- the model is constrained to that set.
    :param retry_delays: Which categories are retried, and how long to wait
        before each. Defaults to :data:`DEFAULT_RETRY_DELAYS`. A category
        absent from the mapping fails the task; a ``None`` delay retries
        without overriding the task's own ``retry_delay`` and backoff.
        Passing this **replaces** the default mapping rather than merging
        into it, so pass every category you want retried.
    :param fallback_rules: Optional list of
        :class:`~airflow.sdk.definitions.retry_policy.RetryRule` applied when the
        LLM call fails. Provides a deterministic safety net.
    :param timeout: Maximum seconds to wait for the LLM response before
        falling back.  Defaults to 30s.  The LLM provider's own timeout
        (e.g. 600s for Anthropic) is much longer; this keeps the retry
        decision path fast even when the provider is degraded.
    :param redactor: Callable applied to the exception's string representation
        before it is added to the classification prompt. Defaults to
        :func:`~airflow.providers.common.ai.policies.retry.redact_registered_secrets`,
        which only masks values already registered via ``mask_secret()``.
        Pass a custom callable to replace the default masking entirely --
        for example to redact free-text PII the secrets masker cannot see.
        To disable masking altogether, use ``redact_exception=False`` --
        not ``redactor=None``.
    :param redact_exception: Whether to redact the exception's string
        representation before it is added to the classification prompt.
        Defaults to ``True``. Set to ``False`` to send the raw exception
        text as-is. Passing ``redact_exception=False`` together with
        an explicit ``redactor`` raises ``ValueError`` at construction time,
        since the two settings would otherwise conflict silently.
    :param max_exception_length: Maximum number of characters of the
        (already redacted) exception message included in the prompt. Longer
        messages are truncated with a trailing ``"... (truncated)"`` marker.
        Must be a positive integer. Defaults to 4096.

    .. warning::
        The exception's string representation is sent to the configured
        external LLM provider (OpenAI, Anthropic, Bedrock, Vertex, Ollama,
        etc.) as part of the classification prompt, so it may leak whatever
        the failing task put in the exception message — connection strings,
        credential fragments, PII, or other secrets. By default
        ``_classify()`` runs the message through
        :func:`~airflow.providers.common.ai.policies.retry.redact_registered_secrets`
        via ``redactor``, which masks values already registered via
        ``mask_secret()`` (for example, connection passwords Airflow
        captured while resolving the failing task's connections). This does
        **not** perform general-purpose PII detection and will not catch
        arbitrary sensitive strings that were never registered as secrets --
        for free-text PII (emails, customer names, etc.) supply your own
        ``redactor``, or pass ``redact_exception=False`` to disable
        redaction altogether. You are still responsible for confirming that
        your task's exception messages are safe to send to a third-party
        LLM provider.
    """

    def __init__(
        self,
        llm_conn_id: str,
        model_id: str | None = None,
        instructions: str | None = None,
        fallback_rules: list[RetryRule] | None = None,
        timeout: float = 30.0,
        *,
        retry_delays: Mapping[ErrorCategory, timedelta | None] | None = None,
        redactor: Callable[[str], str] | None = None,
        redact_exception: bool = True,
        max_exception_length: int = 4096,
    ) -> None:
        if max_exception_length <= 0:
            raise ValueError(f"max_exception_length must be a positive integer, got {max_exception_length}")
        if retry_delays is not None:
            unknown = sorted(set(retry_delays) - set(ERROR_CATEGORIES))
            if unknown:
                raise ValueError(
                    f"retry_delays names categories the classifier cannot return: {unknown}. "
                    f"Valid categories are {list(ERROR_CATEGORIES)}."
                )
            mistyped = sorted(
                f"{category}={delay!r}"
                for category, delay in retry_delays.items()
                if delay is not None and not isinstance(delay, timedelta)
            )
            if mistyped:
                raise ValueError(
                    f"retry_delays values must be timedelta or None, got {mistyped}. "
                    f"Use timedelta(seconds=60) rather than 60."
                )
            negative = sorted(
                category
                for category, delay in retry_delays.items()
                if delay is not None and delay < timedelta(0)
            )
            if negative:
                raise ValueError(f"retry_delays must not be negative, got negative delays for {negative}.")
        if not redact_exception and redactor is not None:
            raise ValueError(
                "redactor must not be set when redact_exception=False -- passing an explicit "
                "redactor while also disabling redaction is contradictory. Either drop "
                "redact_exception=False to keep using redactor, or drop redactor to disable "
                "redaction entirely."
            )
        self.llm_conn_id = llm_conn_id
        self.model_id = model_id
        self.instructions = instructions or DEFAULT_INSTRUCTIONS
        self.fallback_rules = fallback_rules
        self.timeout = timeout
        # dict() on both branches: DEFAULT_RETRY_DELAYS is a mappingproxy, which cannot be
        # deep-copied, and sharing a policy through ``TaskGroup(default_args=...)`` does
        # deep-copy it.
        self.retry_delays: Mapping[ErrorCategory, timedelta | None] = dict(
            DEFAULT_RETRY_DELAYS if retry_delays is None else retry_delays
        )
        self.redactor: Callable[[str], str] | None = (
            None if not redact_exception else redactor if redactor is not None else redact_registered_secrets
        )
        self.redact_exception = redact_exception
        self.max_exception_length = max_exception_length

    def evaluate(
        self,
        exception: BaseException,
        try_number: int,
        max_tries: int,
        context: Context | None = None,
    ) -> RetryDecision:
        try:
            return self._classify(exception, try_number, max_tries)
        except Exception:
            log.exception("LLM retry classification failed, using fallback")
            if self.fallback_rules:
                return ExceptionRetryPolicy(rules=self.fallback_rules).evaluate(
                    exception, try_number, max_tries, context
                )
            return RetryDecision.default()

    def _classify(
        self,
        exception: BaseException,
        try_number: int,
        max_tries: int,
    ) -> RetryDecision:
        from airflow.providers.common.ai.hooks.pydantic_ai import PydanticAIHook

        hook = PydanticAIHook(llm_conn_id=self.llm_conn_id, model_id=self.model_id)
        agent = hook.create_agent(
            output_type=ErrorClassification,
            instructions=self.instructions,
        )

        # Redact before truncating -- truncating first could cut a registered secret in half.
        message = self.redactor(str(exception)) if self.redactor is not None else str(exception)
        if len(message) > self.max_exception_length:
            message = f"{message[: self.max_exception_length]}... (truncated)"
        prompt = (
            f"Classify this error from a data pipeline task "
            f"(attempt {try_number} of {max_tries}):\n\n"
            f"{type(exception).__name__}: {message}"
        )

        from pydantic_ai.settings import ModelSettings

        result = agent.run_sync(
            prompt,
            model_settings=ModelSettings(timeout=self.timeout),
        )
        classification = result.output
        category = classification.category
        reason = f"{category}: {classification.reasoning}"

        if category not in self.retry_delays:
            log.info(
                "LLM error classification: category=%s, retry=no (retried categories: %s), reasoning=%s",
                category,
                ", ".join(sorted(self.retry_delays)) or "none",
                classification.reasoning,
            )
            return RetryDecision.fail(reason=reason)

        delay = self.retry_delays[category]
        log.info(
            "LLM error classification: category=%s, retry=yes, delay=%s, reasoning=%s",
            category,
            delay if delay is not None else "task default",
            classification.reasoning,
        )
        return RetryDecision.retry(delay=delay, reason=reason)
