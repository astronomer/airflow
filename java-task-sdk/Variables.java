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

//
// Variables
// Handles the Airflow Variables needed by the Task for execution
// Supports reading from a local file for ease of testing and debugging
//
// TODO: Add support to get from API server. 

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

import org.json.JSONObject;

public class Variables {
    private final Map<String, String> vars;

    public Variables() {
        this.vars = new HashMap<>();
    }

    public void put(String name, String value) {
        vars.put(name, value);
    }

    public String get(String name) {
        return vars.get(name);
    }

    @Override
    public String toString() {
        return vars.toString();
    }

    public JSONObject toJson() {
        return new JSONObject(vars);
    }

    public static Variables fromJson(JSONObject json) {
        Variables v = new Variables();
        for (String key : json.keySet()) {
            v.put(key, json.getString(key));
        }
        return v;
    }

    public void writeToFile(String filePath) throws IOException {
        try (FileWriter fw = new FileWriter(filePath)) {
            fw.write(toJson().toString(2));
        }
    }

    public static Variables fromFile(String filePath) throws IOException {
        File file = new File(filePath);
        if (!file.exists()) return new Variables();
        String content = Files.readString(file.toPath());
        return fromJson(new JSONObject(content));
    }
}

