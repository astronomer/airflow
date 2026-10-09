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
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import sysconfig
import textwrap

import argcomplete
import pytest

from airflow.cli import cli_parser, completion_cache

AIRFLOW_COMMAND = os.path.join(os.path.dirname(sys.executable), "airflow")


class _CompletionDone(Exception):
    pass


def _exit(code: int = 0) -> None:
    raise _CompletionDone


def _complete(parser: argparse.ArgumentParser, line: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("_ARGCOMPLETE", "1")
    monkeypatch.setenv("COMP_LINE", line)
    monkeypatch.setenv("COMP_POINT", str(len(line)))
    monkeypatch.setenv("_ARGCOMPLETE_IFS", "\n")
    output = io.StringIO()
    with pytest.raises(_CompletionDone):
        argcomplete.CompletionFinder()(parser, exit_method=_exit, output_stream=output)
    return sorted(output.getvalue().split("\n"))


def _cached_parser(spec: list) -> argparse.ArgumentParser:
    return completion_cache._load_parser(
        json.loads(json.dumps(spec)), argparse.ArgumentParser(prog="airflow", add_help=False)
    )


def _subcommand_helps(parser: argparse.ArgumentParser) -> dict[str, str | None]:
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {choice.dest: choice.help for choice in subparsers._choices_actions}


def _completion_env(airflow_home, line: str) -> dict[str, str]:
    return {
        **os.environ,
        "_ARGCOMPLETE": "1",
        "COMP_LINE": line,
        "COMP_POINT": str(len(line)),
        "_ARGCOMPLETE_IFS": "\n",
        "_ARGCOMPLETE_STDOUT_FILENAME": os.fspath(airflow_home / "completions"),
    }


def _store_parser_with_flag_only_in_cache() -> None:
    parser = argparse.ArgumentParser(prog="airflow")
    parser.add_argument("--only-in-cache")
    completion_cache.store(parser)


@pytest.fixture
def parser_spec():
    return completion_cache._dump_parser(cli_parser.get_parser())


@pytest.fixture
def airflow_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRFLOW_HOME", os.fspath(tmp_path))
    monkeypatch.delenv("AIRFLOW_CONFIG", raising=False)
    monkeypatch.setattr(completion_cache, "_startup_fingerprint", None)
    return tmp_path


def _without_choices(spec: list) -> list:
    """Drop ``choices``, which the cached parser offers through completers instead."""
    stripped = []
    for action in spec:
        if action["kind"] == "subcommands":
            subcommands = [
                {**sub, "parser": _without_choices(sub["parser"])} for sub in action["subcommands"]
            ]
            stripped.append({**action, "subcommands": subcommands})
        else:
            stripped.append({**action, "choices": None})
    return stripped


def test_cached_parser_keeps_every_command_and_flag(parser_spec):
    assert completion_cache._dump_parser(_cached_parser(parser_spec)) == _without_choices(parser_spec)


def test_cached_parser_accepts_values_the_real_parser_converts(parser_spec, tmp_path, monkeypatch):
    # ``--serialization-format`` lower-cases its value before checking it against the choices.
    (tmp_path / "connections.env").write_text("")
    line = f"airflow connections export --serialization-format JSON {tmp_path}/conn"

    real = _complete(cli_parser.get_parser.__wrapped__(), line, monkeypatch)
    cached = _complete(_cached_parser(parser_spec), line, monkeypatch)

    assert real == [f"{tmp_path}/connections.env "]
    assert cached == real


def test_cached_parser_keeps_command_descriptions(parser_spec):
    helps = _subcommand_helps(_cached_parser(parser_spec))

    assert helps == _subcommand_helps(cli_parser.get_parser())
    assert helps["dags"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("airflow da", ["dag-processor", "dags"]),
        ("airflow dags l", ["list", "list-import-errors", "list-jobs", "list-runs"]),
        ("airflow dags list --o", ["--output "]),
        ("airflow dags list --output ", ["json", "plain", "table", "yaml"]),
        ("airflow dags list -o j", ["json "]),
        ("airflow jobs check --job-type ", ["DagProcessorJob", "SchedulerJob", "TriggererJob"]),
        ("airflow --", ["--help "]),
    ],
)
def test_cached_parser_completes_like_the_real_parser(parser_spec, monkeypatch, line, expected):
    # argcomplete patches the parsers it walks and never restores them, so each completion gets a
    # parser of its own.
    real = _complete(cli_parser.get_parser.__wrapped__(), line, monkeypatch)
    cached = _complete(_cached_parser(parser_spec), line, monkeypatch)

    assert real == expected
    assert cached == real


@pytest.mark.parametrize("line", ["airflow tasks test --", "airflow config ", "airflow pools set "])
def test_cached_parser_completes_open_ended_lines_like_the_real_parser(parser_spec, monkeypatch, line):
    real = _complete(cli_parser.get_parser.__wrapped__(), line, monkeypatch)
    cached = _complete(_cached_parser(parser_spec), line, monkeypatch)

    assert cached == real


def test_load_parser_returns_stored_parser(airflow_home):
    completion_cache.store(cli_parser.get_parser())

    assert completion_cache.load_parser(completion_cache._fingerprint()) is not None


@pytest.mark.parametrize(
    "env_var",
    [
        "AIRFLOW__CORE__EXECUTOR",
        "AIRFLOW__CORE__AUTH_MANAGER",
        "AIRFLOW__CORE__MULTI_TEAM",
        "AIRFLOW_PACKAGE_NAME",
        "PYTHONPATH",
    ],
)
def test_fingerprint_changes_with_environment(airflow_home, monkeypatch, env_var):
    before = completion_cache._fingerprint()

    monkeypatch.setenv(env_var, os.fspath(airflow_home / "changed"))

    assert completion_cache._fingerprint() != before


def test_fingerprint_changes_when_a_distribution_is_installed(airflow_home, tmp_path, monkeypatch):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    monkeypatch.setattr(sysconfig, "get_path", lambda name: os.fspath(site_packages))
    before = completion_cache._fingerprint()

    (site_packages / "apache_airflow_providers_new-1.0.0.dist-info").mkdir()
    stat = site_packages.stat()
    os.utime(site_packages, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert completion_cache._fingerprint() != before


def test_fingerprint_changes_when_cli_definitions_change(airflow_home, tmp_path, monkeypatch):
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    cli_config = cli_dir / "cli_config.py"
    cli_config.write_text("")
    monkeypatch.setattr(completion_cache, "__file__", os.fspath(cli_dir / "completion_cache.py"))
    before = completion_cache._fingerprint()

    stat = cli_config.stat()
    os.utime(cli_config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert completion_cache._fingerprint() != before


def test_fingerprint_changes_with_python_version(airflow_home, monkeypatch):
    before = completion_cache._fingerprint()

    monkeypatch.setattr(sys, "version", "0.0.0")

    assert completion_cache._fingerprint() != before


@pytest.mark.parametrize("config_file_env", [None, "$AIRFLOW_HOME/custom.cfg"])
def test_fingerprint_changes_when_config_file_changes(airflow_home, monkeypatch, config_file_env):
    config_file = airflow_home / ("airflow.cfg" if config_file_env is None else "custom.cfg")
    if config_file_env is not None:
        monkeypatch.setenv("AIRFLOW_CONFIG", config_file_env)
    config_file.write_text("[core]\n")
    before = completion_cache._fingerprint()

    stat = config_file.stat()
    os.utime(config_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert completion_cache._fingerprint() != before


def test_store_keys_cache_by_environment_before_startup(airflow_home, monkeypatch):
    completion_cache._startup_fingerprint = completion_cache._fingerprint()
    # Reading configuration can export options as environment variables while Airflow starts up.
    monkeypatch.setenv("AIRFLOW__CORE__EXECUTOR", "LocalExecutor")
    completion_cache.store(cli_parser.get_parser())
    monkeypatch.delenv("AIRFLOW__CORE__EXECUTOR")

    assert completion_cache.load_parser(completion_cache._fingerprint()) is not None


def test_writing_the_cache_does_not_invalidate_it(airflow_home, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.fspath(airflow_home))

    completion_cache.store(cli_parser.get_parser())

    assert completion_cache.load_parser(completion_cache._fingerprint()) is not None


@pytest.mark.parametrize("content", ["{not json", "[]", "null", '{"parser": []}'])
def test_load_parser_ignores_unreadable_cache(airflow_home, content):
    (airflow_home / "cli_completion_cache.json").write_text(content)

    assert completion_cache.load_parser(completion_cache._fingerprint()) is None


def test_load_parser_ignores_cache_with_malformed_parser(airflow_home):
    fingerprint = completion_cache._fingerprint()
    (airflow_home / "cli_completion_cache.json").write_text(
        json.dumps({"fingerprint": fingerprint, "parser": [{"kind": "store"}]})
    )

    assert completion_cache.load_parser(fingerprint) is None


def test_store_ignores_unwritable_airflow_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRFLOW_HOME", os.fspath(tmp_path / "missing"))

    completion_cache.store(cli_parser.get_parser())

    assert not (tmp_path / "missing").exists()


def test_airflow_command_stores_cache_when_completing_without_one(airflow_home):
    subprocess.run(
        [AIRFLOW_COMMAND],
        env=_completion_env(airflow_home, "airflow dags list --o"),
        check=True,
        capture_output=True,
        timeout=120,
    )

    # argcomplete appends a space after a single completion so the shell moves to the next word.
    assert (airflow_home / "completions").read_text().strip() == "--output"
    assert completion_cache.load_parser(completion_cache._fingerprint()) is not None


def test_airflow_command_completes_from_cache(airflow_home):
    _store_parser_with_flag_only_in_cache()

    subprocess.run(
        [AIRFLOW_COMMAND],
        env=_completion_env(airflow_home, "airflow --only"),
        check=True,
        capture_output=True,
        timeout=120,
    )

    assert (airflow_home / "completions").read_text().strip() == "--only-in-cache"


@pytest.mark.parametrize(("program", "uses_cache"), [("/usr/local/bin/airflow", True), ("my-tool", False)])
def test_only_the_airflow_command_completes_from_cache(airflow_home, program, uses_cache):
    _store_parser_with_flag_only_in_cache()
    code = textwrap.dedent(
        f"""
        import sys

        sys.argv[0] = {program!r}
        import airflow

        print("imported airflow")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=_completion_env(airflow_home, "airflow --only"),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert ("imported airflow" not in result.stdout) is uses_cache


def test_running_a_command_does_not_store_cache(airflow_home):
    subprocess.run([AIRFLOW_COMMAND, "version"], check=True, capture_output=True, timeout=120)

    assert not (airflow_home / "cli_completion_cache.json").exists()
