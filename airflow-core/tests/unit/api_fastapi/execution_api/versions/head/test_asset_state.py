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

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select

from airflow.models.asset import AssetModel
from airflow.models.asset_state import AssetStateModel
from airflow.utils.session import create_session

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db_test


@pytest.fixture(autouse=True)
def reset_state_tables():
    with create_session() as session:
        session.execute(delete(AssetStateModel))
        session.execute(delete(AssetModel))


@pytest.fixture
def asset(session: Session) -> AssetModel:
    asset = AssetModel(name="test_asset", uri="s3://bucket/test", group="asset")
    session.add(asset)
    session.commit()
    return asset


def _api_url(asset_id: int, key: str | None = None) -> str:
    base = f"/execution/state/asset/{asset_id}"
    return f"{base}/{key}" if key else base


class TestGetAssetState:
    def test_get_returns_value(self, client: TestClient, asset: AssetModel):
        client.put(_api_url(asset.id, "watermark"), json={"value": "2026-04-29"})

        response = client.get(_api_url(asset.id, "watermark"))

        assert response.status_code == 200
        assert response.json() == {"value": "2026-04-29"}

    def test_get_missing_key_returns_404(self, client: TestClient, asset: AssetModel):
        response = client.get(_api_url(asset.id, "never_set"))

        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "not_found"


class TestPutAssetState:
    def test_put_creates_row(self, client: TestClient, asset: AssetModel):
        response = client.put(_api_url(asset.id, "watermark"), json={"value": "2026-04-29"})

        assert response.status_code == 204
        with create_session() as session:
            row = session.scalar(
                select(AssetStateModel).where(
                    AssetStateModel.asset_id == asset.id,
                    AssetStateModel.key == "watermark",
                )
            )
            assert row is not None
            assert row.value == "2026-04-29"

    def test_put_overwrites_existing(self, client: TestClient, asset: AssetModel):
        client.put(_api_url(asset.id, "watermark"), json={"value": "2026-04-28"})

        response = client.put(_api_url(asset.id, "watermark"), json={"value": "2026-04-29"})

        assert response.status_code == 204
        assert client.get(_api_url(asset.id, "watermark")).json() == {"value": "2026-04-29"}

    def test_put_empty_body_returns_422(self, client: TestClient, asset: AssetModel):
        response = client.put(_api_url(asset.id, "watermark"), json={})

        assert response.status_code == 422

    def test_put_extra_field_returns_422(self, client: TestClient, asset: AssetModel):
        response = client.put(_api_url(asset.id, "watermark"), json={"value": "x", "extra": "y"})

        assert response.status_code == 422

    def test_put_unknown_asset_returns_404(self, client: TestClient):
        response = client.put(_api_url(999999, "watermark"), json={"value": "x"})

        assert response.status_code == 404
        assert "999999" in response.json()["detail"]["message"]


class TestDeleteAssetState:
    def test_delete_removes_key(self, client: TestClient, asset: AssetModel):
        client.put(_api_url(asset.id, "watermark"), json={"value": "2026-04-29"})

        response = client.delete(_api_url(asset.id, "watermark"))

        assert response.status_code == 204
        assert client.get(_api_url(asset.id, "watermark")).status_code == 404

    def test_delete_missing_key_is_noop(self, client: TestClient, asset: AssetModel):
        response = client.delete(_api_url(asset.id, "never_existed"))

        assert response.status_code == 204


class TestClearAssetState:
    def test_clear_removes_all_keys(self, client: TestClient, asset: AssetModel):
        for k, v in [("watermark", "a"), ("last_id", "b"), ("schema_hash", "c")]:
            client.put(_api_url(asset.id, k), json={"value": v})

        response = client.delete(_api_url(asset.id))

        assert response.status_code == 204
        with create_session() as session:
            row = session.scalar(select(AssetStateModel).where(AssetStateModel.asset_id == asset.id))
            assert row is None
