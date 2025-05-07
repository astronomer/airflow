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
// TaskRegistry
//
// Handless the collection of Java Tasks which can be run
// Includes operations for registering a new Task 
// and executing a new Task once it has been registered
//
// Key thing to note is that the uniqueness is based on DagID + Task Name
//

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.function.BiFunction;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

//
// TaskRegistry
//
// Helper class which contains the list of Tasks which can be performed
// This includes a way to "register" the available Tasks and then to execute them
//
// Currently supported Tasks are: Hello
//

public class TaskRegistry {

    // set up a logging mechanism
    private static final Logger logger = LogManager.getLogger(TaskRegistry.class);

    // set up a private registry structure
    private final Map<String, Map<String, BiFunction<InputContext, String, XcomData>>> functionMap;

    public TaskRegistry() {
        this.functionMap = new HashMap<>();
        logger.info("TaskRegistry initialized");
    }

    public void registerTask(String dagID, String taskName, BiFunction<InputContext, String, XcomData> function) {
        functionMap.computeIfAbsent(dagID, k -> new HashMap<>()).put(taskName, function);
 
        logger.info("Registered function for task [{}] in DAG [{}]", taskName, dagID);
    }

    public XcomData execTask(String dagID, String taskName, InputContext inputContext) throws IOException {
        logger.debug("Getting configuration for task [{}] in DAG [{}]", taskName, dagID);

        Map<String, BiFunction<InputContext, String, XcomData>> taskMap = functionMap.get(dagID);
        if (taskMap == null) {
            logger.error("No tasks found for DAG ID [{}]", dagID);
            throw new IOException("No tasks registered for DAG ID: " + dagID);
        }

        BiFunction<InputContext, String, XcomData> function = taskMap.get(taskName);
        if (function == null) {
            logger.error("No task [{}] found in DAG [{}]", taskName, dagID);
            throw new IOException("No task found with name: " + taskName + " in DAG ID: " + dagID);
        }

        logger.info("Executing task [{}] in DAG [{}]", taskName, dagID);
        XcomData result = function.apply(inputContext, taskName);
        logger.debug("Task [{}] in DAG [{}] returned result: {}", taskName, dagID, result);
        return result;
    }
}

