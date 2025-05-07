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
// XcomData
// Handles the XcomData needed by the Task for reading and also writing for
// later tasks. Though those will be two separate copies. 
//
// Supports reading/writing from a local file for ease of testing and debugging
//
// TODO: Add support to get/put from API server. 

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

import org.json.JSONObject;

public class XcomData {
    private final Map<String, String> data;

    public XcomData() {
        this.data = new HashMap<>();
    }

    public void put(String name, String value) {
        data.put(name, value);
    }

    public String get(String name) {
        return data.get(name);
    }

    @Override
    public String toString() {
        return data.toString();
    }

    public JSONObject toJson() {
        return new JSONObject(data);
    }

    public static XcomData fromJson(JSONObject json) {
        XcomData xcom = new XcomData();
        for (String key : json.keySet()) {
            xcom.put(key, json.getString(key));
        }
        return xcom;
    }

    public void writeToFile(String filePath) throws IOException {
        try (FileWriter fw = new FileWriter(filePath)) {
            fw.write(toJson().toString(2));
        }
    }

    public static XcomData fromFile(String filePath) throws IOException {
        File file = new File(filePath);
        if (!file.exists()) return new XcomData();
        String content = Files.readString(file.toPath());
        return fromJson(new JSONObject(content));
    }
}

