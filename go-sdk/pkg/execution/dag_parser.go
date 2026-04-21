// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package execution

import (
	"github.com/apache/airflow/go-sdk/sdk"
)

// ParseDags processes a DagFileParseRequest by serializing all DAGs in the bundle
// to DagSerialization v3 format and returning the result as a DagFileParsingResult map.
func ParseDags(bundle *sdk.Bundle, req *DagFileParseRequest) map[string]any {
	fileloc := req.File
	bundlePath := req.BundlePath
	relativeFileloc := computeRelativeFileloc(fileloc, bundlePath)

	serializedDags := make([]any, 0, len(bundle.Dags))
	for _, dag := range bundle.OrderedDags() {
		serializedDag := SerializeDag(dag, fileloc, relativeFileloc)
		serializedDags = append(serializedDags, map[string]any{
			"data": map[string]any{
				"__version": 3,
				"dag":       serializedDag,
			},
		})
	}

	return map[string]any{
		"type":            "DagFileParsingResult",
		"fileloc":         fileloc,
		"serialized_dags": serializedDags,
	}
}
