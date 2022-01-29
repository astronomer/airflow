/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/* global fetch */

import { useState, useEffect, useCallback } from 'react';
import camelcaseKeys from 'camelcase-keys';

import getMetaValue from '../../utils';

// dagId comes from dag.html
const dagId = getMetaValue('dag_id');
const graphDataUrl = getMetaValue('graph_data');
const urlRoot = getMetaValue('root');

const formatData = (data) => {
  if (!data || !Object.keys(data).length) {
    return {
      groups: {},
      dagRuns: [],
    };
  }
  let formattedData = data;
  // Convert to json if needed
  if (typeof data === 'string') formattedData = JSON.parse(data);
  // change from pacal to camelcase
  formattedData = camelcaseKeys(formattedData, { deep: true });
  return formattedData;
};

const useGraphData = () => {
  const [data, setData] = useState();

  const handleRefresh = useCallback(async () => {
    try {
      const root = urlRoot ? `&root=${urlRoot}` : '';
      const resp = await fetch(`${graphDataUrl}?dag_id=${dagId}${root}`);
      let newData = await resp.json();
      console.log(newData);
      if (newData) {
        newData = formatData(newData);
        if (JSON.stringify(newData) !== JSON.stringify(data)) {
          setData(newData);
        }
      }
    } catch (e) {
      console.error(e);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    handleRefresh();
  }, [handleRefresh]);

  return {
    data,
  };
};

export default useGraphData;
