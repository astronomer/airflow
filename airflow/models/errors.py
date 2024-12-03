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

from typing import TYPE_CHECKING

from sqlalchemy import Column, Integer, String, Text, delete

from airflow.models.base import Base
from airflow.utils import timezone
from airflow.utils.session import NEW_SESSION, provide_session
from airflow.utils.sqlalchemy import UtcDateTime

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ParseImportError(Base):
    """Stores all Import Errors which are recorded when parsing DAGs and displayed on the Webserver."""

    __tablename__ = "import_error"
    id = Column(Integer, primary_key=True)
    timestamp = Column(UtcDateTime)
    filename = Column(String(1024))
    stacktrace = Column(Text)
    processor_subdir = Column(String(2000), nullable=True)

    @classmethod
    @provide_session
    def update_import_errors(
        cls,
        filename: str,
        import_errors: dict[str, str],
        processor_subdir: str | None = None,
        session: Session = NEW_SESSION,
    ) -> None:
        """
        Update any import errors to be displayed in the UI.

        For the DAGs in the given DagBag, record any associated import errors and clears
        errors for files that no longer have them. These are usually displayed through the
        Airflow UI so that users know that there are issues parsing DAGs.
        :param processor_subdir:
        :param filename:
        :param import_errors: Dictionary containing the import errors
        :param session: session for ORM operations
        """
        from airflow.listeners.listener import get_listener_manager
        from airflow.models.dag import DagModel

        # Clear the errors of the processed files
        # that no longer have errors
        if not import_errors:
            session.execute(
                delete(ParseImportError)
                .where(ParseImportError.filename.startswith(filename))
                .execution_options(synchronize_session="fetch")
            )
            return
        existing_import_errors = session.query(ParseImportError.filename).filter(
            ParseImportError.filename == filename).all()

        # Add the errors of the processed files
        # TODO Should we modify this to assume just one import error per file? What happens if there are multiple for one file?
        for filename, stacktrace in import_errors.items():
            if filename in existing_import_errors:
                session.query(ParseImportError).filter(ParseImportError.filename == filename).update(
                    {"filename": filename, "timestamp": timezone.utcnow(), "stacktrace": stacktrace},
                    synchronize_session="fetch",
                )
                # sending notification when an existing dag import error occurs
                get_listener_manager().hook.on_existing_dag_import_error(
                    filename=filename, stacktrace=stacktrace
                )
            else:
                session.add(
                    ParseImportError(
                        filename=filename,
                        timestamp=timezone.utcnow(),
                        stacktrace=stacktrace,
                        processor_subdir=processor_subdir,
                    )
                )
                # sending notification when a new dag import error occurs
                get_listener_manager().hook.on_new_dag_import_error(filename=filename, stacktrace=stacktrace)
            (
                session.query(DagModel)
                .filter(DagModel.fileloc == filename)
                .update({"has_import_errors": True}, synchronize_session="fetch")
            )

        session.commit()
        session.flush()
