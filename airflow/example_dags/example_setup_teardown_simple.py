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
"""Example DAG demonstrating the usage of setup and teardown tasks."""
from __future__ import annotations

import pendulum

from airflow.example_dags.example_skip_dag import EmptySkipOperator
from airflow.models.baseoperator import BaseOperator
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.task_group import TaskGroup


class EmptyFailOperator(BaseOperator):
    """Fails."""

    def execute(self, context):
        raise ValueError("i fail")


with DAG(
    dag_id="example_setup_teardown_simple",
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    catchup=False,
    tags=["example"],
) as dag:
    with TaskGroup("dag_setup", is_setup=True) as dag_setup:
        root_setup1 = BashOperator.as_setup(
            task_id="root_setup_1", bash_command="sleep 5 && echo 'Hello from root_setup'"
        )
        root_setup2 = BashOperator.as_setup(
            task_id="root_setup_2", bash_command="sleep 5 && echo 'Hello from root_setup'"
        )
    normal = BashOperator(task_id="normal", bash_command="sleep 5 && echo 'I am just a normal task'")
    skip_op = EmptySkipOperator(task_id="skip_op")
    skip_normal_op = EmptySkipOperator(task_id="skip_normal_op")
    skip_setup = BashOperator.as_setup(task_id="skip_setup", bash_command="sleep 5")
    skip_teardown = BashOperator.as_teardown(task_id="skip_teardown", bash_command="sleep 5")
    normal >> skip_op >> skip_setup >> skip_normal_op >> skip_teardown
    skip_setup >> skip_teardown
    fail_op = EmptyFailOperator(task_id="fail_op")
    fail_normal_op = EmptyFailOperator(task_id="fail_normal_op")
    fail_setup = BashOperator.as_setup(task_id="fail_setup", bash_command="sleep 5")
    fail_teardown = BashOperator.as_teardown(task_id="fail_teardown", bash_command="sleep 5")
    normal >> fail_op >> fail_setup >> fail_normal_op >> fail_teardown
    fail_setup >> fail_teardown
    # todo: currently we ignore setup >> teardown directly. but maybe should only do that when dag>>teardown
    #  or perhaps throw error in that case. right now, setup >> teardown is silently ignored.
    with TaskGroup("section_1") as section_1:
        s_setup = BashOperator.as_setup(
            task_id="taskgroup_setup", bash_command="sleep 5 && echo 'Hello from taskgroup_setup'"
        )
        s_normal = BashOperator(task_id="normal", bash_command="sleep 5 && exit 1")
        s_teardown = BashOperator.as_teardown(
            task_id="taskgroup_teardown",
            bash_command="sleep 5 && echo 'Hello from taskgroup_teardown'",
        )

        s_setup >> s_normal >> s_teardown
        # s_setup >> s_teardown

    list(section_1.get_leaves())
    assert list(x.task_id for x in section_1.get_leaves()) == ["section_1.normal"]
    normal2 = BashOperator(task_id="normal2", bash_command="sleep 5 && echo 'I am just another normal task'")
    with TaskGroup("dag_teardown", is_teardown=True) as dag_teardown:
        root_teardown1 = BashOperator.as_teardown(
            task_id="root_teardown1",
            bash_command="sleep 5 && echo 'Goodbye from root_teardown'",
        )
        root_teardown2 = BashOperator.as_teardown(
            task_id="root_teardown2",
            bash_command="sleep 5 && echo 'Goodbye from root_teardown'",
        )

    dag_setup >> normal >> section_1 >> normal2 >> dag_teardown
    root_setup1 >> root_teardown1
    root_setup2 >> root_teardown2
    root_setup1.downstream_list
    print(normal2.downstream_list)
    # assert [x.task_id for x in normal2.upstream_list] == ["section_1.normal"]
    print(root_setup1.get_serialized_fields())
    s_teardown.upstream_list
    s_teardown.trigger_rule

dag_teardown.upstream_list
list(dag_teardown.get_roots())
dag_teardown.upstream_list
list(section_1.get_roots())
section_1.downstream_task_ids
#
# # dag_teardown.is_teardown = False
# dag_teardown.roots
# normal2.downstream_list
# from pprint import pprint
#
# # pprint(BaseSerialization.serialize(dag_teardown))
# # pprint(task_group_to_dict(dag_teardown))
# # pprint(dag_teardown.get_task_group_dict())
# assert dag_edges(dag) == [
#     {"source_id": "dag_setup.downstream_join_id", "target_id": "normal"},
#     {"source_id": "dag_setup.root_setup_1", "target_id": "dag_setup.downstream_join_id"},
#     {"source_id": "dag_setup.root_setup_1", "target_id": "dag_teardown.root_teardown1"},
#     {"source_id": "dag_setup.root_setup_2", "target_id": "dag_setup.downstream_join_id"},
#     {"source_id": "dag_setup.root_setup_2", "target_id": "dag_teardown.root_teardown2"},
#     {"source_id": "dag_teardown.upstream_join_id", "target_id": "dag_teardown.root_teardown1"},
#     {"source_id": "dag_teardown.upstream_join_id", "target_id": "dag_teardown.root_teardown2"},
#     {"source_id": "fail_normal_op", "target_id": "fail_teardown"},
#     {"source_id": "fail_op", "target_id": "fail_setup"},
#     {"source_id": "fail_setup", "target_id": "fail_normal_op"},
#     {"source_id": "fail_setup", "target_id": "fail_teardown"},
#     {"source_id": "normal", "target_id": "fail_op"},
#     {"source_id": "normal", "target_id": "section_1.upstream_join_id"},
#     {"source_id": "normal", "target_id": "skip_op"},
#     {"source_id": "normal2", "target_id": "dag_teardown.upstream_join_id"},
#     {"source_id": "section_1.downstream_join_id", "target_id": "normal2"},
#     {"source_id": "section_1.normal", "target_id": "section_1.downstream_join_id"},
#     {"source_id": "section_1.normal", "target_id": "section_1.taskgroup_teardown"},
#     {"source_id": "section_1.taskgroup_setup", "target_id": "section_1.normal"},
#     {"source_id": "section_1.taskgroup_setup", "target_id": "section_1.taskgroup_teardown"},
#     {"source_id": "section_1.upstream_join_id", "target_id": "section_1.taskgroup_setup"},
#     {"source_id": "skip_normal_op", "target_id": "skip_teardown"},
#     {"source_id": "skip_op", "target_id": "skip_setup"},
#     {"source_id": "skip_setup", "target_id": "skip_normal_op"},
#     {"source_id": "skip_setup", "target_id": "skip_teardown"},
# ]
# serialized = SerializedDAG.serialize(dag)
# deser = SerializedDAG.deserialize_dag(serialized)
# reser = SerializedDAG.serialize(deser)
# for k, v in reser.items():
#     other = serialized[k]
#     if not v == other:
#         print(k, v)
# pprint(reser["tasks"])
# these = serialized["tasks"]
# others = reser["tasks"]
# these = {x["task_id"]: x for x in these}
# others = {x["task_id"]: x for x in others}
#
# len(these)
# len(others)
# for task_id, task in these.items():
#     for k, v in task.items():
#         other_one = others[task_id].get(k, "n/a")
#         if not v == other_one:
#             print(k, v, other_one)
#
# assert dag_edges(deser) == [
#     {"source_id": "dag_setup.downstream_join_id", "target_id": "normal"},
#     {"source_id": "dag_setup.root_setup_1", "target_id": "dag_setup.downstream_join_id"},
#     {"source_id": "dag_setup.root_setup_1", "target_id": "dag_teardown.root_teardown1"},
#     {"source_id": "dag_setup.root_setup_2", "target_id": "dag_setup.downstream_join_id"},
#     {"source_id": "dag_setup.root_setup_2", "target_id": "dag_teardown.root_teardown2"},
#     {"source_id": "dag_teardown.upstream_join_id", "target_id": "dag_teardown.root_teardown1"},
#     {"source_id": "dag_teardown.upstream_join_id", "target_id": "dag_teardown.root_teardown2"},
#     {"source_id": "fail_normal_op", "target_id": "fail_teardown"},
#     {"source_id": "fail_op", "target_id": "fail_setup"},
#     {"source_id": "fail_setup", "target_id": "fail_normal_op"},
#     {"source_id": "fail_setup", "target_id": "fail_teardown"},
#     {"source_id": "normal", "target_id": "fail_op"},
#     {"source_id": "normal", "target_id": "section_1.upstream_join_id"},
#     {"source_id": "normal", "target_id": "skip_op"},
#     {"source_id": "normal2", "target_id": "dag_teardown.upstream_join_id"},
#     {"source_id": "section_1.downstream_join_id", "target_id": "normal2"},
#     {"source_id": "section_1.normal", "target_id": "section_1.downstream_join_id"},
#     {"source_id": "section_1.normal", "target_id": "section_1.taskgroup_teardown"},
#     {"source_id": "section_1.taskgroup_setup", "target_id": "section_1.normal"},
#     {"source_id": "section_1.taskgroup_setup", "target_id": "section_1.taskgroup_teardown"},
#     {"source_id": "section_1.upstream_join_id", "target_id": "section_1.taskgroup_setup"},
#     {"source_id": "skip_normal_op", "target_id": "skip_teardown"},
#     {"source_id": "skip_op", "target_id": "skip_setup"},
#     {"source_id": "skip_setup", "target_id": "skip_normal_op"},
#     {"source_id": "skip_setup", "target_id": "skip_teardown"},
# ]
# pprint([x for x in dag_edges(dag) if "dag_teardown" in x["source_id"] + x["target_id"]])
# import json
# for k, v in serialized.items():
#     print(f"assert json.dumps(serialized['{k}']) == '{json.dumps(v)}'")
#
# assert json.dumps(serialized['dataset_triggers']) == '[]'
# assert json.dumps(serialized['catchup']) == 'false'
# assert json.dumps(serialized['fileloc']) == '"<input>"'
# assert json.dumps(serialized['_dag_id']) == '"example_setup_teardown_simple"'
# assert json.dumps(serialized['edge_info']) == '{}'
# assert json.dumps(serialized['timezone']) == '"UTC"'
# assert json.dumps(serialized['schedule_interval']) == '{"__var": 86400.0, "__type": "timedelta"}'
# assert json.dumps(serialized['tags']) == '["example"]'
# assert json.dumps(serialized['start_date']) == '1609459200.0'
# assert json.dumps(serialized['_task_group']) == '{"_group_id": null, "prefix_group_id": true, "tooltip": "", "ui_color": "CornflowerBlue", "ui_fgcolor": "#000", "children": {"dag_setup": ["taskgroup", {"_group_id": "dag_setup", "prefix_group_id": true, "tooltip": "", "ui_color": "CornflowerBlue", "ui_fgcolor": "#000", "children": {"dag_setup.root_setup_1": ["operator", "dag_setup.root_setup_1"], "dag_setup.root_setup_2": ["operator", "dag_setup.root_setup_2"]}, "upstream_group_ids": [], "downstream_group_ids": [], "upstream_task_ids": [], "downstream_task_ids": ["normal"]}], "normal": ["operator", "normal"], "skip_op": ["operator", "skip_op"], "skip_normal_op": ["operator", "skip_normal_op"], "skip_setup": ["operator", "skip_setup"], "skip_teardown": ["operator", "skip_teardown"], "fail_op": ["operator", "fail_op"], "fail_normal_op": ["operator", "fail_normal_op"], "fail_setup": ["operator", "fail_setup"], "fail_teardown": ["operator", "fail_teardown"], "section_1": ["taskgroup", {"_group_id": "section_1", "prefix_group_id": true, "tooltip": "", "ui_color": "CornflowerBlue", "ui_fgcolor": "#000", "children": {"section_1.taskgroup_setup": ["operator", "section_1.taskgroup_setup"], "section_1.normal": ["operator", "section_1.normal"], "section_1.taskgroup_teardown": ["operator", "section_1.taskgroup_teardown"]}, "upstream_group_ids": [], "downstream_group_ids": [], "upstream_task_ids": ["normal"], "downstream_task_ids": ["normal2"]}], "normal2": ["operator", "normal2"], "dag_teardown": ["taskgroup", {"_group_id": "dag_teardown", "prefix_group_id": true, "tooltip": "", "ui_color": "CornflowerBlue", "ui_fgcolor": "#000", "children": {"dag_teardown.root_teardown1": ["operator", "dag_teardown.root_teardown1"], "dag_teardown.root_teardown2": ["operator", "dag_teardown.root_teardown2"]}, "upstream_group_ids": [], "downstream_group_ids": [], "upstream_task_ids": ["normal2"], "downstream_task_ids": []}]}, "upstream_group_ids": [], "downstream_group_ids": [], "upstream_task_ids": [], "downstream_task_ids": []}'
# assert json.dumps(serialized['_processor_dags_folder']) == '"/Users/dstandish/airflow/dags"'
# assert json.dumps(serialized['tasks']) == """[{"task_id": "dag_setup.root_setup_1", "_is_setup": true, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["dag_teardown.root_teardown1", "normal"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Hello from root_setup'"}, {"task_id": "dag_setup.root_setup_2", "_is_setup": true, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["dag_teardown.root_teardown2", "normal"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Hello from root_setup'"}, {"task_id": "normal", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["fail_op", "section_1.taskgroup_setup", "skip_op"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'I am just a normal task'"}, {"task_id": "skip_op", "_is_setup": false, "template_ext": [], "ui_color": "#e8b7e4", "pool": "default_pool", "downstream_task_ids": ["skip_setup"], "ui_fgcolor": "#000", "template_fields": [], "_is_teardown": false, "template_fields_renderers": {}, "_task_type": "EmptySkipOperator", "_task_module": "airflow.example_dags.example_skip_dag", "_is_empty": false}, {"task_id": "skip_normal_op", "_is_setup": false, "template_ext": [], "ui_color": "#e8b7e4", "pool": "default_pool", "downstream_task_ids": ["skip_teardown"], "ui_fgcolor": "#000", "template_fields": [], "_is_teardown": false, "template_fields_renderers": {}, "_task_type": "EmptySkipOperator", "_task_module": "airflow.example_dags.example_skip_dag", "_is_empty": false}, {"task_id": "skip_setup", "_is_setup": true, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["skip_normal_op", "skip_teardown"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5"}, {"task_id": "skip_teardown", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": [], "ui_fgcolor": "#000", "trigger_rule": "all_done_setup_success", "template_fields": ["bash_command", "env"], "_is_teardown": true, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5"}, {"task_id": "fail_op", "_is_setup": false, "template_ext": [], "ui_color": "#fff", "pool": "default_pool", "downstream_task_ids": ["fail_setup"], "ui_fgcolor": "#000", "template_fields": [], "_is_teardown": false, "template_fields_renderers": {}, "_task_type": "EmptyFailOperator", "_task_module": "__main__", "_is_empty": false}, {"task_id": "fail_normal_op", "_is_setup": false, "template_ext": [], "ui_color": "#fff", "pool": "default_pool", "downstream_task_ids": ["fail_teardown"], "ui_fgcolor": "#000", "template_fields": [], "_is_teardown": false, "template_fields_renderers": {}, "_task_type": "EmptyFailOperator", "_task_module": "__main__", "_is_empty": false}, {"task_id": "fail_setup", "_is_setup": true, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["fail_normal_op", "fail_teardown"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5"}, {"task_id": "fail_teardown", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": [], "ui_fgcolor": "#000", "trigger_rule": "all_done_setup_success", "template_fields": ["bash_command", "env"], "_is_teardown": true, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5"}, {"task_id": "section_1.taskgroup_setup", "_is_setup": true, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["section_1.normal", "section_1.taskgroup_teardown"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Hello from taskgroup_setup'"}, {"task_id": "section_1.normal", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["normal2", "section_1.taskgroup_teardown"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && exit 1"}, {"task_id": "section_1.taskgroup_teardown", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": [], "ui_fgcolor": "#000", "trigger_rule": "all_done_setup_success", "template_fields": ["bash_command", "env"], "_is_teardown": true, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Hello from taskgroup_teardown'"}, {"task_id": "normal2", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": ["dag_teardown.root_teardown1", "dag_teardown.root_teardown2"], "ui_fgcolor": "#000", "template_fields": ["bash_command", "env"], "_is_teardown": false, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'I am just another normal task'"}, {"task_id": "dag_teardown.root_teardown1", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": [], "ui_fgcolor": "#000", "trigger_rule": "all_done_setup_success", "template_fields": ["bash_command", "env"], "_is_teardown": true, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Goodbye from root_teardown'"}, {"task_id": "dag_teardown.root_teardown2", "_is_setup": false, "template_ext": [".sh", ".bash"], "ui_color": "#f0ede4", "pool": "default_pool", "downstream_task_ids": [], "ui_fgcolor": "#000", "trigger_rule": "all_done_setup_success", "template_fields": ["bash_command", "env"], "_is_teardown": true, "template_fields_renderers": {"bash_command": "bash", "env": "json"}, "_task_type": "BashOperator", "_task_module": "airflow.operators.bash", "_is_empty": false, "bash_command": "sleep 5 && echo 'Goodbye from root_teardown'"}]"""
# assert json.dumps(serialized['dag_dependencies']) == '[]'
# assert json.dumps(serialized['params']) == '{}'
# pprint(serialized['tasks'])
