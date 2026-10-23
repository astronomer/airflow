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
from unittest import mock

import pytest
import time_machine

from airflow.providers.common.compat.sdk import Asset, ObjectStoragePath
from airflow.providers.common.io.checkpoints import Checkpoints

from tests_common.test_utils.config import conf_vars

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
    def _make(run_id="run_1", map_index=-1, try_number=1, asset_stores=None, **kwargs):
        ti = SimpleNamespace(
            dag_id="train_dag", run_id=run_id, task_id="train", map_index=map_index, try_number=try_number
        )
        stores = {BEST_MODEL: asset_store} if asset_stores is None else asset_stores
        kwargs.setdefault("base", base)
        kwargs.setdefault("best_model_ref", BEST_MODEL)
        context = {"ti": ti, "asset_state_store": stores}
        with mock.patch("airflow.providers.common.io.checkpoints.get_current_context", return_value=context):
            return Checkpoints(**kwargs)

    return _make


def save(ckpt, step, loss, at):
    with time_machine.travel(T0 + timedelta(minutes=at), tick=False):
        with ckpt.save(step=step, metrics={"loss": loss}) as folder:
            (folder / "weights.bin").write_bytes(f"weights-{step}".encode())


def test_save_uploads_files_then_writes_record(make_ckpt):
    ckpt = make_ckpt(label="lr=0.1")
    with ckpt.save(step=5, metrics={"loss": 0.6}) as folder:
        (folder / "weights.bin").write_bytes(b"w")
        (folder / "sub").mkdir()
        (folder / "sub" / "opt.bin").write_bytes(b"o")

    record = ckpt.latest()
    assert record["step"] == 5
    assert record["metrics"] == {"loss": 0.6}
    assert record["label"] == "lr=0.1"
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
        ("latest", False, "newest"),
        ("best", False, "best"),
        ("by_id", False, "newest"),
        ("best", True, "own"),
    ],
    ids=["fresh-starts-empty", "latest", "best", "exact-id", "retry-wins-over-start"],
)
def test_resume(make_ckpt, start, own_checkpoint, expected):
    old_run = make_ckpt(run_id="run_0")
    save(old_run, 5, 0.3, at=0)
    best = old_run.latest()
    old_run.set_best(best)
    save(old_run, 10, 0.5, at=1)
    newest = old_run.latest()

    if own_checkpoint:
        save(make_ckpt(), 15, 0.4, at=2)

    ckpt = make_ckpt(start=newest["id"] if start == "by_id" else start, try_number=2)
    record = ckpt.resume()

    if expected is None:
        assert record is None
    else:
        expected_record = {"best": best, "newest": newest, "own": ckpt.latest()}[expected]
        assert record == expected_record
        save(ckpt, 20, 0.2, at=3)
        assert ckpt.latest()["parent"] == expected_record["id"]


def test_latest_matches_label_not_position(make_ckpt):
    save(make_ckpt(run_id="run_0", map_index=0, label="a"), 5, 0.5, at=0)
    save(make_ckpt(run_id="run_0", map_index=1, label="b"), 5, 0.6, at=1)

    # The next run lists the same labels in a different order.
    ckpt = make_ckpt(run_id="run_1", map_index=1, label="a", start="latest")
    assert ckpt.resume()["label"] == "a"


def test_latest_needs_label_for_mapped_tasks(make_ckpt):
    with pytest.raises(ValueError, match="need a label"):
        make_ckpt(map_index=0, start="latest")


def test_base_defaults_to_config(make_ckpt, base):
    with conf_vars({("common.io", "checkpoints_path"): base}):
        ckpt = make_ckpt(base=None)
    assert str(ckpt.root) == str(ObjectStoragePath(base) / "train_dag")


@conf_vars({("common.io", "checkpoints_path"): ""})
def test_missing_base_raises(make_ckpt):
    with pytest.raises(ValueError, match="checkpoints_path"):
        make_ckpt(base=None)


def test_best_model_ref_missing_from_task_raises(make_ckpt):
    ckpt = make_ckpt(asset_stores={})
    with pytest.raises(ValueError, match="inlets or outlets"):
        ckpt.best()


def test_find_filters(make_ckpt):
    save(make_ckpt(map_index=0, label="a"), 5, 0.6, at=0)
    save(make_ckpt(map_index=0, label="a"), 10, 0.5, at=1)
    save(make_ckpt(map_index=1, label="b"), 5, 0.7, at=2)
    save(make_ckpt(run_id="run_2", map_index=0, label="a"), 5, 0.4, at=3)

    finder = make_ckpt()
    assert [r["step"] for r in finder.find(label="a")] == [5, 10, 5]
    assert [r["step"] for r in finder.find(label="a", limit=2)] == [5, 10]
    latest = finder.find(run_id="run_1", latest_per_task=True)
    assert [(r["label"], r["step"]) for r in latest] == [("b", 5), ("a", 10)]
    good = finder.find(where=lambda r: r["metrics"]["loss"] < 0.55)
    assert [(r["run_id"], r["step"]) for r in good] == [("run_2", 5), ("run_1", 10)]


def test_cleanup_keeps_newest_and_best_across_runs(make_ckpt):
    run_1 = make_ckpt(run_id="run_1")
    save(run_1, 5, 0.2, at=0)
    best = run_1.latest()
    run_1.set_best(best)
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


def test_background_saves_record_in_order(make_ckpt):
    with make_ckpt() as ckpt:
        for step in (5, 10):
            with ckpt.save(step=step, background=True) as folder:
                (folder / "weights.bin").write_bytes(f"w{step}".encode())
            local = folder

    first, second = sorted(ckpt.find(), key=lambda r: r["step"])
    assert second["parent"] == first["id"]
    assert (ObjectStoragePath(second["path"]) / "weights.bin").read_bytes() == b"w10"
    assert not local.exists()


def background_save(ckpt):
    with ckpt.save(step=5, background=True) as folder:
        (folder / "weights.bin").write_bytes(b"w")


@mock.patch(
    "airflow.providers.common.io.checkpoints._copy", autospec=True, side_effect=OSError("upload failed")
)
def test_background_upload_error_is_raised_and_leaves_no_record(mock_copy, make_ckpt):
    ckpt = make_ckpt()
    with pytest.raises(OSError, match="upload failed"):
        with ckpt:
            background_save(ckpt)
    assert ckpt.find() == []


def test_background_save_needs_with_block(make_ckpt):
    with pytest.raises(ValueError, match="with Checkpoints"):
        background_save(make_ckpt())


def test_history_survives_cleanup(make_ckpt):
    run_0 = make_ckpt(run_id="run_0")
    save(run_0, 5, 0.6, at=0)
    save(run_0, 10, 0.5, at=1)
    run_1 = make_ckpt(run_id="run_1", start="latest")
    run_1.resume()
    save(run_1, 15, 0.4, at=2)
    save(run_1, 20, 0.3, at=3)

    removed = run_1.cleanup(keep_last=1)

    assert [r["step"] for r in run_1.history(run_1.latest())] == [20, 15, 10, 5]
    assert [r["step"] for r in run_1.find()] == [20]
    assert not any(ObjectStoragePath(run_1.get(i)["path"]).exists() for i in removed)


@pytest.mark.parametrize("background", [False, True])
def test_keep_last_prunes_after_each_save_but_keeps_best(make_ckpt, background):
    with make_ckpt(keep_last=1) as ckpt:
        save(ckpt, 5, 0.2, at=0)
        ckpt.set_best(ckpt.latest())
        for step, at in ((10, 1), (15, 2), (20, 3)):
            with time_machine.travel(T0 + timedelta(minutes=at), tick=False):
                with ckpt.save(step=step, metrics={"loss": 0.5}, background=background) as folder:
                    (folder / "weights.bin").write_bytes(b"w")

    assert [r["step"] for r in ckpt.find()] == [20, 5]
    assert [r["step"] for r in ckpt.history(ckpt.latest())] == [20, 15, 10, 5]
