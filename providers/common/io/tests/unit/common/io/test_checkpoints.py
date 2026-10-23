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

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import time_machine

from airflow.providers.common.compat.sdk import Asset, ObjectStoragePath
from airflow.providers.common.io.checkpoints import Checkpoints

BEST_MODEL = Asset("best_model")
T0 = datetime(2026, 10, 23, tzinfo=UTC)


class FakeAssetStore:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


@pytest.fixture
def base(tmp_path):
    return f"file://{tmp_path / 'store'}"


@pytest.fixture
def asset_store():
    return FakeAssetStore()


@pytest.fixture
def make_ckpt(base, asset_store):
    def _make(run_id="run_1", map_index=-1, try_number=1, **kwargs):
        ti = SimpleNamespace(
            dag_id="train_dag", run_id=run_id, task_id="train", map_index=map_index, try_number=try_number
        )
        context = {"ti": ti, "asset_state_store": {BEST_MODEL: asset_store}}
        return Checkpoints(base, best_model=BEST_MODEL, context=context, **kwargs)

    return _make


def save(ckpt, step, loss, at):
    with time_machine.travel(T0 + timedelta(minutes=at), tick=False):
        with ckpt.save(step=step, metrics={"loss": loss}) as folder:
            (folder / "weights.bin").write_bytes(f"weights-{step}".encode())


def test_save_uploads_files_then_writes_record(make_ckpt):
    ckpt = make_ckpt(trial="lr=0.1")
    with ckpt.save(step=5, metrics={"loss": 0.6}) as folder:
        (folder / "weights.bin").write_bytes(b"w")
        (folder / "sub").mkdir()
        (folder / "sub" / "opt.bin").write_bytes(b"o")

    record = ckpt.latest()
    assert record["step"] == 5
    assert record["metrics"] == {"loss": 0.6}
    assert record["trial"] == "lr=0.1"
    assert record["parent"] is None
    assert (ObjectStoragePath(record["path"]) / "sub" / "opt.bin").read_bytes() == b"o"
    with ckpt.load(record) as local:
        assert (local / "weights.bin").read_bytes() == b"w"
        assert (local / "sub" / "opt.bin").read_bytes() == b"o"


def crash_mid_save(ckpt):
    with ckpt.save(step=5) as folder:
        (folder / "weights.bin").write_bytes(b"half")
        raise RuntimeError("crash mid-save")


def test_failed_save_writes_no_record(make_ckpt):
    ckpt = make_ckpt()
    with pytest.raises(RuntimeError, match="crash mid-save"):
        crash_mid_save(ckpt)

    assert ckpt.find() == []
    assert ckpt.resume() is None


@pytest.mark.parametrize(
    ("start", "own_checkpoint", "expected"),
    [
        ("fresh", False, None),
        ("best", False, "best"),
        ("by_id", False, "old"),
        ("best", True, "own"),
    ],
    ids=["fresh-starts-empty", "best", "exact-id", "retry-wins-over-start"],
)
def test_resume(make_ckpt, start, own_checkpoint, expected):
    old_run = make_ckpt(run_id="run_0")
    save(old_run, 5, 0.5, at=0)
    old = old_run.latest()
    save(old_run, 10, 0.3, at=1)
    best = old_run.latest()
    old_run.promote_if_better(best, metric="loss", lower_is_better=True)

    if own_checkpoint:
        save(make_ckpt(), 15, 0.4, at=2)

    ckpt = make_ckpt(start=old["id"] if start == "by_id" else start, try_number=2)
    record = ckpt.resume()

    if expected is None:
        assert record is None
    else:
        expected_record = {"best": best, "old": old, "own": ckpt.latest()}[expected]
        assert record == expected_record
        save(ckpt, 20, 0.2, at=3)
        assert ckpt.latest()["parent"] == expected_record["id"]


def test_find_filters_across_runs_and_latest_only(make_ckpt):
    save(make_ckpt(map_index=0, trial="a"), 5, 0.6, at=0)
    save(make_ckpt(map_index=0, trial="a"), 10, 0.5, at=1)
    save(make_ckpt(map_index=1, trial="b"), 5, 0.7, at=2)
    save(make_ckpt(run_id="run_2", map_index=0, trial="a"), 5, 0.4, at=3)

    finder = make_ckpt()
    assert [r["step"] for r in finder.find(trial="a")] == [5, 10, 5]
    latest = finder.find(run_id="run_1", latest_only=True)
    assert [(r["trial"], r["step"]) for r in latest] == [("b", 5), ("a", 10)]


@pytest.mark.parametrize(
    ("lower_is_better", "new_value", "promoted"),
    [
        (True, 0.3, True),
        (True, 0.5, False),
        (True, 0.7, False),
        (False, 0.7, True),
        (False, 0.3, False),
    ],
)
def test_promote_if_better(make_ckpt, asset_store, lower_is_better, new_value, promoted):
    ckpt = make_ckpt()
    save(ckpt, 5, 0.5, at=0)
    current = ckpt.latest()
    assert ckpt.promote_if_better(current, metric="loss", lower_is_better=lower_is_better)

    save(ckpt, 10, new_value, at=1)
    new = ckpt.latest()

    assert ckpt.promote_if_better(new, metric="loss", lower_is_better=lower_is_better) is promoted
    assert asset_store.get("best_checkpoint") == (new if promoted else current)["id"]


def test_cleanup_keeps_newest_and_best_across_runs(make_ckpt):
    run_1 = make_ckpt(run_id="run_1")
    save(run_1, 5, 0.2, at=0)
    best = run_1.latest()
    run_1.promote_if_better(best, metric="loss", lower_is_better=True)
    save(run_1, 10, 0.5, at=1)
    save(make_ckpt(run_id="run_2"), 5, 0.6, at=2)
    save(make_ckpt(run_id="run_2"), 10, 0.4, at=3)
    save(make_ckpt(run_id="run_2", map_index=1), 5, 0.9, at=4)

    ckpt = make_ckpt()
    removed = ckpt.cleanup(keep_last=2)

    remaining = ckpt.find()
    assert {(r["run_id"], r["map_index"], r["step"]) for r in remaining} == {
        ("run_2", -1, 10),
        ("run_2", -1, 5),
        ("run_1", -1, 5),
        ("run_2", 1, 5),
    }
    assert len(removed) == 1
    assert not ObjectStoragePath(f"{ckpt.root}/ckpts/{removed[0]}").exists()
