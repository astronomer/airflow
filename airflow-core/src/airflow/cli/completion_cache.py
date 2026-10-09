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
Shell completion for the ``airflow`` command, served from a cached description of its parser.

Each key press that argcomplete completes runs the ``airflow`` console script, which imports the
``airflow`` package and initializes configuration, logging, the ORM and providers before argcomplete
can answer. The parser it completes against only changes when installed packages, the CLI
definitions or the executor and auth manager configuration change, so after one completion that
builds the parser the slow way, :func:`store` saves a JSON description of it and
:func:`complete_from_cache` answers later completions from a plain :mod:`argparse` parser rebuilt
from that description.

:func:`complete_from_cache` runs from ``airflow/__init__.py`` before anything else in Airflow is
imported, so this module must only import the standard library and argcomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import site
import sys
import sysconfig
from contextlib import suppress
from typing import Literal, NotRequired, TypedDict

import argcomplete

# Bump when the layout written by ``_dump_parser`` changes, so caches from older versions are ignored.
_FORMAT_VERSION = 1

# Environment that changes which CLI commands exist: executors and auth managers from providers that
# predate the ``cli`` section of provider info contribute commands based on the first three, and
# ``AIRFLOW_PACKAGE_NAME`` (set when building docs) leaves out provider commands.
_COMMAND_SET_ENV_VARS = (
    "AIRFLOW__CORE__EXECUTOR",
    "AIRFLOW__CORE__AUTH_MANAGER",
    "AIRFLOW__CORE__MULTI_TEAM",
    "AIRFLOW_PACKAGE_NAME",
)

# The fingerprint of the environment as it was before Airflow started up, which can change it
# (configuration parsing sets environment variables, for example). ``store`` reuses it, so a cache
# written after startup matches the next completion, which checks it before startup.
_startup_fingerprint: str | None = None


class _ArgumentSpec(TypedDict):
    """An optional or positional argument, as much of it as argcomplete reads."""

    kind: Literal["help", "version", "flag", "store"]
    flags: list[str]
    dest: str
    nargs: int | str | None
    choices: list[str] | None
    help: str | None
    metavar: str | list[str] | None
    required: bool


class _SubcommandSpec(TypedDict):
    name: str
    parser: list[_ActionSpec]
    # Absent for commands hidden from help, which argparse registers without a help entry.
    help: NotRequired[str | None]


class _SubcommandsSpec(TypedDict):
    kind: Literal["subcommands"]
    dest: str | None
    metavar: str | None
    required: bool
    subcommands: list[_SubcommandSpec]


_ActionSpec = _ArgumentSpec | _SubcommandsSpec


def _expand(path: str) -> str:
    # Same expansion as ``airflow.configuration``: repeat until nested variables are resolved.
    while (expanded := os.path.expanduser(os.path.expandvars(path))) != path:
        path = expanded
    return path


def _airflow_home() -> str:
    return _expand(os.environ.get("AIRFLOW_HOME", "~/airflow"))


def _config_file() -> str:
    if (config_file := os.environ.get("AIRFLOW_CONFIG")) is None:
        return os.path.join(_airflow_home(), "airflow.cfg")
    return _expand(config_file)


def _cache_path() -> str:
    return os.path.join(_airflow_home(), "cli_completion_cache.json")


def _fingerprint() -> str:
    """Return a key that changes whenever the set of CLI commands, flags or choices can change."""
    cli_dir = os.path.dirname(os.path.abspath(__file__))
    # Installing, upgrading or removing a distribution adds or removes its ``.dist-info`` directory,
    # which updates the modification time of the directory it is installed into. ``sys.path`` itself
    # is not used, as Airflow adds the config and plugins folders to it while starting up.
    watched = [
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
        site.getusersitepackages(),
        *os.environ.get("PYTHONPATH", "").split(os.pathsep),
        os.path.join(cli_dir, "cli_config.py"),
        os.path.join(cli_dir, "cli_parser.py"),
        _config_file(),
    ]
    # Writing the cache updates the modification time of its own directory.
    cache_dir = os.path.dirname(_cache_path())
    digest = hashlib.sha256(f"{_FORMAT_VERSION}\0{sys.version}\0".encode())
    for path in watched:
        if path and os.path.abspath(path) == cache_dir:
            continue
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = -1
        digest.update(f"{path}\0{mtime}\0".encode())
    for name in _COMMAND_SET_ENV_VARS:
        digest.update(f"{name}={os.environ.get(name, '')}\0".encode())
    return digest.hexdigest()


def _text(value: object) -> str | None:
    # Help strings may be lazy proxies, which are resolved here so they can be written as JSON.
    return None if value is None else str(value)


def _dump_parser(parser: argparse.ArgumentParser) -> list[_ActionSpec]:
    actions: list[_ActionSpec] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            subcommands: list[_SubcommandSpec] = []
            for name, subparser in action.choices.items():
                subcommand: _SubcommandSpec = {"name": name, "parser": _dump_parser(subparser)}
                if name in helps:
                    subcommand["help"] = _text(helps[name])
                subcommands.append(subcommand)
            actions.append(
                {
                    "kind": "subcommands",
                    "dest": action.dest,
                    "metavar": _text(action.metavar),
                    "required": action.required,
                    "subcommands": subcommands,
                }
            )
            continue
        kind: Literal["help", "version", "flag", "store"]
        if isinstance(action, argparse._HelpAction):
            kind = "help"
        elif isinstance(action, argparse._VersionAction):
            kind = "version"
        elif action.nargs == 0:
            kind = "flag"
        else:
            kind = "store"
        actions.append(
            {
                "kind": kind,
                "flags": list(action.option_strings),
                "dest": action.dest,
                "nargs": action.nargs,
                # argcomplete completes choices by their ``str()``.
                "choices": None if action.choices is None else [str(choice) for choice in action.choices],
                "help": _text(action.help),
                "metavar": list(action.metavar) if isinstance(action.metavar, tuple) else action.metavar,
                "required": action.required,
            }
        )
    return actions


def _add_argument(parser: argparse.ArgumentParser, argument: _ArgumentSpec) -> None:
    flags, help_text = argument["flags"], argument["help"]
    if argument["kind"] == "help":
        parser.add_argument(*flags, action="help", help=help_text)
    elif argument["kind"] == "version":
        parser.add_argument(*flags, action="version", version="", help=help_text)
    elif argument["kind"] == "flag":
        parser.add_argument(
            *flags, action="store_true", dest=argument["dest"], required=argument["required"], help=help_text
        )
    else:
        nargs, metavar = argument["nargs"], argument["metavar"]
        value_metavar = tuple(metavar) if isinstance(metavar, list) else metavar
        if flags:
            action = parser.add_argument(
                *flags,
                dest=argument["dest"],
                required=argument["required"],
                nargs=nargs,
                metavar=value_metavar,
                help=help_text,
            )
        else:
            action = parser.add_argument(argument["dest"], nargs=nargs, metavar=value_metavar, help=help_text)
        if (choices := argument["choices"]) is not None:
            # Offered through a completer rather than ``choices``: argparse would also reject values
            # the real parser accepts once its ``type`` converter has run (for example lower-casing).
            action.completer = lambda **kwargs: choices  # type: ignore[attr-defined]


def _load_parser(actions: list[_ActionSpec], parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    for action in actions:
        if action["kind"] != "subcommands":
            _add_argument(parser, action)
            continue
        subparsers = parser.add_subparsers(
            dest=action["dest"], metavar=action["metavar"], required=action["required"]
        )
        for subcommand in action["subcommands"]:
            if "help" in subcommand:
                subparser = subparsers.add_parser(subcommand["name"], add_help=False, help=subcommand["help"])
            else:
                subparser = subparsers.add_parser(subcommand["name"], add_help=False)
            _load_parser(subcommand["parser"], subparser)
    return parser


def store(parser: argparse.ArgumentParser) -> None:
    """Save a description of ``parser`` for :func:`complete_from_cache`, ignoring an unwritable home."""
    path = _cache_path()
    content = {"fingerprint": _startup_fingerprint or _fingerprint(), "parser": _dump_parser(parser)}
    # Written to a temporary file and renamed, so concurrent completions never read a partial cache.
    tmp_path = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(content, f)
        os.replace(tmp_path, path)
    except OSError:
        with suppress(OSError):
            os.remove(tmp_path)


def load_parser(fingerprint: str) -> argparse.ArgumentParser | None:
    """Return the parser rebuilt from the cache, or None if there is no usable cache for ``fingerprint``."""
    try:
        with open(_cache_path()) as f:
            content = json.load(f)
        if content["fingerprint"] != fingerprint:
            return None
        return _load_parser(content["parser"], argparse.ArgumentParser(prog="airflow", add_help=False))
    except Exception:
        # A missing, corrupt or foreign cache file is a miss: completion then builds the real parser
        # and :func:`store` replaces the file.
        return None


def complete_from_cache() -> None:
    """Complete the command line from the cached parser and exit, or return if there is no usable cache."""
    global _startup_fingerprint
    _startup_fingerprint = _fingerprint()
    if (parser := load_parser(_startup_fingerprint)) is None:
        return
    argcomplete.autocomplete(parser)
