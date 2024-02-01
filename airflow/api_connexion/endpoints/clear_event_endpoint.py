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

from marshmallow import ValidationError
from sqlalchemy import select

from airflow.api_connexion.endpoints.request_dict import get_json_request_dict
from airflow.api_connexion.exceptions import AlreadyExists, BadRequest
from airflow.api_connexion.schemas.clear_event_schema import clear_event_schema
from airflow.models.dataset import ClearEvent
from airflow.utils.session import NEW_SESSION, provide_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airflow.api_connexion.types import APIResponse
# from airflow.security import permissions
# from airflow.utils.log.action_logger import action_event_from_permission
# from airflow.www.decorators import action_logging


# @security.requires_access_dag("POST")
@provide_session
# @action_logging(
#     event=action_event_from_permission(
#         prefix=RESOURCE_EVENT_PREFIX,
#         permission=permissions.ACTION_CAN_CREATE,
#     ),
# )
def add_clear_event(*, dag_id: str, session: Session = NEW_SESSION) -> APIResponse:
    body = get_json_request_dict()
    try:
        data = clear_event_schema.load(body)
    except ValidationError as err:
        raise BadRequest(detail=str(err.messages))
    cutoff_time = data["cutoff_time"]

    clear_event = session.scalar(
        select(ClearEvent).where(ClearEvent.dag_id == dag_id, ClearEvent.cutoff_time == cutoff_time).limit(1)
    )
    if not clear_event:
        clear_event = ClearEvent(dag_id=dag_id, cutoff_time=cutoff_time)
        session.add(clear_event)
        session.commit()
        return clear_event_schema.dump(clear_event)
    raise AlreadyExists(detail="Clear event already exists")
