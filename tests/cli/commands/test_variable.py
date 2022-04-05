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
#
import io
import os
import tempfile
import unittest.mock
from contextlib import redirect_stdout

import pytest
from click.testing import CliRunner

from airflow import models
from airflow.cli import cli_parser
from airflow.cli.commands import variable_command
from airflow.cli.commands.variable import variables
from airflow.models import Variable
from tests.test_utils.db import clear_db_variables


class TestCliVariables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dagbag = models.DagBag(include_examples=True)
        cls.parser = cli_parser.get_parser()

    def setUp(self):
        clear_db_variables()

    def tearDown(self):
        clear_db_variables()

    def test_variables_set(self):
        """Test variable_set command"""
        runner = CliRunner()
        runner.invoke(variables, ['set', 'foo', 'bar'])
        assert Variable.get("foo") is not None
        with pytest.raises(KeyError):
            Variable.get("foo1")

    def test_variables_get(self):
        Variable.set('foo', {'foo': 'bar'}, serialize_json=True)

        runner = CliRunner()
        result = runner.invoke(variables, ['get', 'foo'])
        assert '{\n  "foo": "bar"\n}\n' == result.output

    def test_get_variable_default_value(self):
        runner = CliRunner()
        result = runner.invoke(variables, ['get', 'baz', '--default', 'bar'])
        assert "bar\n" == result.output

    def test_get_variable_missing_variable(self):
        runner = CliRunner()
        result = runner.invoke(variables, ['get', 'no-existing-VAR'])
        assert 1 == result.exit_code
        assert 'Variable no-existing-VAR does not exist' == result.output.strip()
           

    def test_variables_set_different_types(self):
        """Test storage of various data types"""
        runner = CliRunner()
        # Set a dict
        runner.invoke(variables, ['set', 'dict', '{"foo": "oops"}'])
        # Set a list
        runner.invoke(variables, ['set', 'list', '["oops"]'])
        # Set str
        runner.invoke(variables, ['set', 'str', 'hello string'])
        # Set int
        runner.invoke(variables, ['set', 'int', '42'])
        # Set float
        runner.invoke(variables, ['set', 'float', '42.0'])
        # Set true
        runner.invoke(variables, ['set', 'true', 'true'])
        # Set false
        runner.invoke(variables, ['set', 'false', 'false'])
        # Set none
        runner.invoke(variables, ['set', 'null', 'null'])

        # Export and then import
        runner.invoke(variables, ['export', 'variables_types.json'])
        runner.invoke(variables, ['import', 'variables_types.json'])
       
        # Assert value
        assert {'foo': 'oops'} == Variable.get('dict', deserialize_json=True)
        assert ['oops'] == Variable.get('list', deserialize_json=True)
        assert 'hello string' == Variable.get('str')  # cannot json.loads(str)
        assert 42 == Variable.get('int', deserialize_json=True)
        assert 42.0 == Variable.get('float', deserialize_json=True)
        assert Variable.get('true', deserialize_json=True) is True
        assert Variable.get('false', deserialize_json=True) is False
        assert Variable.get('null', deserialize_json=True) is None

        os.remove('variables_types.json')

    def test_variables_list(self):
        """Test variable_list command"""
        # Test command is received
        runner = CliRunner()
        runner.invoke(variables, ['list'])

    def test_variables_delete(self):
        """Test variable_delete command"""
        runner = CliRunner()
        runner.invoke(variables, ['set', 'foo', 'bar'])
        runner.invoke(variables, ['delete', 'foo'])
        with pytest.raises(KeyError):
            Variable.get("foo")

    def test_variables_import(self):
        """Test variables_import command"""
        runner = CliRunner()
        result = runner.invoke(variables, ['import', os.devnull])
        assert 1 == result.exit_code
        assert "Invalid variables file" in str(result.exception)
       
    def test_variables_export(self):
        """Test variables_export command"""
        runner = CliRunner()
        runner.invoke(variables, ['export', os.devnull])
      
    def test_variables_isolation(self):
        """Test isolation of variables"""
        with tempfile.NamedTemporaryFile(delete=True) as tmp1, tempfile.NamedTemporaryFile(
            delete=True
        ) as tmp2:

            # First export
            runner = CliRunner()
            runner.invoke(variables, ['set', 'foo', '{"foo":"bar"}'])
            runner.invoke(variables, ['set', 'bar', 'original'])
            runner.invoke(variables, ['export', tmp1.name])
           
            with open(tmp1.name) as first_exp:
                runner.invoke(variables, ['set', 'bar', 'updated'])
                runner.invoke(variables, ['set', 'foo', '{"foo":"oops"}'])
                runner.invoke(variables, ['delete', 'foo'])
                runner.invoke(variables, ['import', tmp1.name])
                
                assert 'original' == Variable.get('bar')
                assert '{\n  "foo": "bar"\n}' == Variable.get('foo')

                # Second export
                runner.invoke(variables, ['export', tmp2.name])
                
                with open(tmp2.name) as second_exp:
                    assert first_exp.read() == second_exp.read()
