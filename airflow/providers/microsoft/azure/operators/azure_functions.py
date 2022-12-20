from __future__ import annotations

import json
from typing import TYPE_CHECKING, Sequence, Any

from airflow.compat.functools import cached_property
from airflow.models import BaseOperator
from providers.microsoft.azure.hooks.azure_function import AzureFunctionsHook

if TYPE_CHECKING:
    from airflow.utils.context import Context


class AzureFunctionsInvokeOperator(BaseOperator):
    """
    Invokes an Azure function. You can invoke a function in azure by making http request

    :param function_name: The name of the Azure function.
    :param function_key: function level auth key.
    :param endpoint_url: endpoint url.
    :param method_type: request type of the Azure function HTTPTrigger type
    :param payload: JSON provided as input to the azure function
    :param azure_function_conn_id: The azure function connection ID to use
    """

    template_fields: Sequence[str] = ("function_name", "payload")
    ui_color = "#ff7300"

    def __init__(
        self,
        *,
        function_name: str,
        function_key: str | None = None,
        endpoint_url: str | None = None,
        method_type: str = "POST",
        payload: dict[str, Any] | str | None = None,
        azure_function_conn_id: str = "azure_functions_default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.function_name = function_name
        self.function_key = function_key
        self.payload = payload
        self.method_type = method_type
        self.endpoint_url = endpoint_url
        self.azure_function_conn_id = azure_function_conn_id

    @cached_property
    def hook(self) -> AzureFunctionHook:
        return AzureFunctionHook(azure_function_conn_id=self.azure_function_conn_id, method=self.method_type)

    def execute(self, context: Context):
        """
        Invokes the target Azure functions from Airflow.

        :return: The response payload from the function, or an error object.
        """
        self.log.info("Invoking Azure function: %s with payload: %s", self.function_name, self.payload)
        response = self.hook.invoke_function(
            function_name=self.function_name,
            function_key=self.function_key,
            payload=self.payload,
            endpoint=self.endpoint_url
        )
        return response
