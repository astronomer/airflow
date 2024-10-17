#!/usr/bin/env python
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

import dataclasses
import pathlib
import re
import sys
from typing import ClassVar, Iterator

from common_precommit_utils import console


@dataclasses.dataclass()
class Entry:
    path: pathlib.Path
    accepted_patterns: ClassVar[list[re.Pattern]]

    def check(self) -> bool:
        return any(p.fullmatch(self.path.name) for p in self.accepted_patterns)


@dataclasses.dataclass()
class NormalEntry(Entry):
    accepted_patterns = [re.compile(r"^test_.+\.py$")]


@dataclasses.dataclass()
class SystemEntry(Entry):
    accepted_patterns = [re.compile(r"^test_.+\.py$"), re.compile(r"^example_.+\.py$")]


def iter_test_files(args: list[str]) -> Iterator[Entry]:
    for arg in args:
        if not arg.endswith(".py"):
            continue
        path = pathlib.Path(arg)
        if arg.startswith("tests/system/"):
            yield SystemEntry(path)
        elif arg.startswith("tests/") or arg.startswith("kubernetes_tests/"):
            yield NormalEntry(path)


def filter_incorrect_test_files(entries: Iterator[Entry]) -> list[Entry]:
    return [entry for entry in entries if not entry.check()]


def report_errors(failures: list[Entry]) -> None:
    console.print("[error]The following test files are named incorrectly.[/error]")
    for failure in failures:
        console.print("*", failure.path)
    console.print(
        "[info]All test files in tests/system must start with 'example_' or 'test_'. "
        "Tests elsewhere must start with 'test_'.[/info]"
    )


if __name__ == "__main__":
    entries = iter_test_files(sys.argv[1:])
    if failures := filter_incorrect_test_files(entries):
        report_errors(failures)
    sys.exit(len(failures))
