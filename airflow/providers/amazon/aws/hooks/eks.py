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

import base64
import sys
import tempfile
from contextlib import contextmanager
from typing import Generator

from botocore.signers import RequestSigner

from airflow.providers.amazon.aws.hooks.base_aws import AwsBaseHook
from airflow.utils import yaml

DEFAULT_PAGINATION_TOKEN = ""
STS_TOKEN_EXPIRES_IN = 60
AUTHENTICATION_API_VERSION = "client.authentication.k8s.io/v1alpha1"
_POD_USERNAME = "aws"
_CONTEXT_NAME = "aws"


class EksHook(AwsBaseHook):
    """
    Interact with Amazon EKS, using the boto3 library.

    Additional arguments (such as ``aws_conn_id``) may be specified and
    are passed down to the underlying AwsBaseHook.

    .. seealso::
        :class:`~airflow.providers.amazon.aws.hooks.base_aws.AwsBaseHook`
    """

    client_type = "eks"

    def __init__(self, *args, **kwargs) -> None:
        kwargs["client_type"] = self.client_type
        super().__init__(*args, **kwargs)

    @contextmanager
    def generate_config_file(
        self,
        eks_cluster_name: str,
        pod_namespace: str | None,
    ) -> Generator[str, None, None]:
        """
        Writes the kubeconfig file given an EKS Cluster.

        :param eks_cluster_name: The name of the cluster to generate kubeconfig file for.
        :param pod_namespace: The namespace to run within kubernetes.
        """
        # Set up the client
        eks_client = self.conn

        # Get cluster details
        cluster = eks_client.describe_cluster(name=eks_cluster_name)
        cluster_cert = cluster["cluster"]["certificateAuthority"]["data"]
        cluster_ep = cluster["cluster"]["endpoint"]

        cluster_config = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [
                {
                    "cluster": {"server": cluster_ep, "certificate-authority-data": cluster_cert},
                    "name": eks_cluster_name,
                }
            ],
            "contexts": [
                {
                    "context": {
                        "cluster": eks_cluster_name,
                        "namespace": pod_namespace,
                        "user": _POD_USERNAME,
                    },
                    "name": _CONTEXT_NAME,
                }
            ],
            "current-context": _CONTEXT_NAME,
            "preferences": {},
            "users": [
                {
                    "name": _POD_USERNAME,
                    "user": {
                        "exec": {
                            "apiVersion": AUTHENTICATION_API_VERSION,
                            "command": sys.executable,
                            "args": [
                                "-m",
                                "airflow.providers.amazon.aws.utils.eks_get_token",
                                *(
                                    ["--region-name", self.region_name]
                                    if self.region_name is not None
                                    else []
                                ),
                                *(
                                    ["--aws-conn-id", self.aws_conn_id]
                                    if self.aws_conn_id is not None
                                    else []
                                ),
                                "--cluster-name",
                                eks_cluster_name,
                            ],
                            "env": [
                                {
                                    "name": "AIRFLOW__LOGGING__LOGGING_LEVEL",
                                    "value": "FATAL",
                                }
                            ],
                            "interactiveMode": "Never",
                        }
                    },
                }
            ],
        }
        config_text = yaml.dump(cluster_config, default_flow_style=False)

        with tempfile.NamedTemporaryFile(mode="w") as config_file:
            config_file.write(config_text)
            config_file.flush()
            yield config_file.name

    def fetch_access_token_for_cluster(self, eks_cluster_name: str) -> str:
        session = self.get_session()
        service_id = self.conn.meta.service_model.service_id
        sts_url = (
            f'https://sts.{session.region_name}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15'
        )

        signer = RequestSigner(
            service_id=service_id,
            region_name=session.region_name,
            signing_name='sts',
            signature_version='v4',
            credentials=session.get_credentials(),
            event_emitter=session.events,
        )

        request_params = {
            'method': 'GET',
            'url': sts_url,
            'body': {},
            'headers': {'x-k8s-aws-id': eks_cluster_name},
            'context': {},
        }

        signed_url = signer.generate_presigned_url(
            request_dict=request_params,
            region_name=session.region_name,
            expires_in=STS_TOKEN_EXPIRES_IN,
            operation_name='',
        )

        base64_url = base64.urlsafe_b64encode(signed_url.encode('utf-8')).decode('utf-8')

        # remove any base64 encoding padding:
        return 'k8s-aws-v1.' + base64_url.rstrip("=")
