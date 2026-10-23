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

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

from tests_common.test_utils.version_compat import AIRFLOW_V_3_3_PLUS

if not AIRFLOW_V_3_3_PLUS:
    pytest.skip("Checkpoint requires Airflow >= 3.3", allow_module_level=True)

from airflow.providers.common.compat.sdk import ObjectStoragePath
from airflow.providers.common.io.checkpoint import Checkpoint

from tests_common.test_utils.config import conf_vars


class FakeTaskState:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


@pytest.fixture
def ckpt_base(tmp_path):
    return f"file://{tmp_path / 'store'}"


@pytest.fixture
def task_state():
    return FakeTaskState()


@pytest.fixture
def make_ckpt(ckpt_base, task_state):
    def _make(try_number=1, **kwargs):
        ti = SimpleNamespace(dag_id="dag", task_id="train", id=uuid.uuid4(), try_number=try_number)
        kwargs.setdefault("base", ckpt_base)
        context = {"ti": ti, "task_state_store": task_state}
        with mock.patch("airflow.providers.common.io.checkpoint.get_current_context", return_value=context):
            return Checkpoint("ckpt", **kwargs)

    return _make


def save(ckpt, step, **kwargs):
    with ckpt.save({"step": step}, **kwargs) as folder:
        (folder / "weights.bin").write_bytes(f"w{step}".encode())
        (folder / "sub").mkdir()
        (folder / "sub" / "opt.bin").write_bytes(b"opt")


def crash_mid_save(ckpt):
    with ckpt.save({"step": 99}) as folder:
        (folder / "weights.bin").write_bytes(b"half")
        raise RuntimeError("crash mid-save")


def restored_step(ckpt):
    with ckpt.restore() as found:
        return found.metadata["step"] if found else None


def test_retry_restores_the_latest_save(make_ckpt):
    first = make_ckpt()
    assert restored_step(first) is None
    save(first, 5)
    save(first, 10)

    retry = make_ckpt(try_number=2)
    with retry.restore() as found:
        assert found.metadata == {"step": 10}
        assert found.try_number == 1
        assert (found.path / "weights.bin").read_bytes() == b"w10"
        assert (found.path / "sub" / "opt.bin").read_bytes() == b"opt"
        local = found.path
    assert not local.exists()


def test_failed_save_keeps_the_previous_checkpoint(make_ckpt):
    ckpt = make_ckpt()
    save(ckpt, 5)
    with pytest.raises(RuntimeError, match="crash mid-save"):
        crash_mid_save(ckpt)

    assert restored_step(make_ckpt(try_number=2)) == 5


@mock.patch(
    "airflow.providers.common.io.checkpoint._upload", autospec=True, side_effect=OSError("upload failed")
)
def test_pointer_is_not_written_when_the_upload_fails(mock_upload, make_ckpt, task_state):
    ckpt = make_ckpt()
    with pytest.raises(OSError, match="upload failed"):
        save(ckpt, 5)
    assert task_state.get("ckpt") is None


def test_background_save_commits_when_the_block_ends(make_ckpt, task_state):
    with make_ckpt() as ckpt:
        save(ckpt, 5, background=True)
        assert task_state.get("ckpt") is None
    assert restored_step(make_ckpt(try_number=2)) == 5


def test_background_save_needs_the_with_block(make_ckpt):
    with pytest.raises(ValueError, match="with Checkpoint"):
        save(make_ckpt(), 5, background=True)


@mock.patch(
    "airflow.providers.common.io.checkpoint._upload", autospec=True, side_effect=OSError("upload failed")
)
def test_background_upload_error_fails_the_block(mock_upload, make_ckpt, task_state):
    ckpt = make_ckpt()
    with pytest.raises(OSError, match="upload failed"):
        with ckpt:
            save(ckpt, 5, background=True)
    assert task_state.get("ckpt") is None


def test_keep_removes_older_saves(make_ckpt):
    ckpt = make_ckpt(keep=2)
    for step in (1, 2, 3):
        save(ckpt, step)
    assert sorted(p.name for p in ckpt.root.iterdir()) == ["v2", "v3"]


def test_save_folder_uploads_a_folder_written_by_a_library(make_ckpt, tmp_path):
    library_dir = tmp_path / "checkpoint-500"
    library_dir.mkdir()
    (library_dir / "model.safetensors").write_bytes(b"model")
    make_ckpt().save_folder(library_dir, {"step": 500})

    assert (library_dir / "model.safetensors").exists()
    with make_ckpt(try_number=2).restore() as found:
        assert found.metadata == {"step": 500}
        assert (found.path / "model.safetensors").read_bytes() == b"model"


def test_engine_writes_to_next_path_then_commits(make_ckpt):
    ckpt = make_ckpt()
    path = ckpt.next_path()
    path.mkdir(parents=True)
    (path / "shard-0.bin").write_bytes(b"s0")
    ckpt.commit(path, {"step": 7})

    with make_ckpt(try_number=2).restore() as found:
        assert found.metadata == {"step": 7}
        assert (found.path / "shard-0.bin").read_bytes() == b"s0"


def test_warm_start_is_used_only_without_a_saved_checkpoint(make_ckpt, ckpt_base):
    warm = ObjectStoragePath(ckpt_base) / "models" / "v12"
    warm.mkdir(parents=True)
    (warm / "weights.bin").write_bytes(b"warm")

    ckpt = make_ckpt(warm_start=str(warm))
    with ckpt.restore() as found:
        assert (found.path / "weights.bin").read_bytes() == b"warm"
        assert found.try_number is None

    save(ckpt, 5)
    assert restored_step(make_ckpt(try_number=2, warm_start=str(warm))) == 5


def test_restore_raises_when_saved_files_were_removed(make_ckpt, task_state):
    save(make_ckpt(), 5)
    ObjectStoragePath(task_state.get("ckpt")["path"]).rmdir(recursive=True)

    with pytest.raises(FileNotFoundError, match="removed after they were saved"):
        restored_step(make_ckpt(try_number=2))


def test_restore_raises_when_warm_start_has_no_files(make_ckpt, ckpt_base):
    ckpt = make_ckpt(warm_start=f"{ckpt_base}/models/missing")
    with pytest.raises(FileNotFoundError, match="warm_start folder"):
        restored_step(ckpt)


def save_nothing(ckpt):
    with ckpt.save({"step": 1}):
        pass


def test_empty_folder_is_never_saved_or_committed(make_ckpt, task_state, tmp_path):
    ckpt = make_ckpt()
    with pytest.raises(ValueError, match="Nothing to save"):
        save_nothing(ckpt)
    with pytest.raises(ValueError, match="Nothing to save"):
        ckpt.save_folder(tmp_path, {"step": 1})
    with pytest.raises(ValueError, match="Nothing to commit"):
        ckpt.commit(ckpt.next_path(), {"step": 1})
    assert task_state.get("ckpt") is None


@conf_vars({("common.io", "checkpoints_path"): ""})
def test_missing_base_raises(make_ckpt):
    with pytest.raises(ValueError, match="checkpoints_path"):
        make_ckpt(base=None)
