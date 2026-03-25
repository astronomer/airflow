/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * JVM entry point for SparkStandaloneExecutor drivers.
 *
 * Spark Standalone cluster deploy mode does not support Python applications
 * directly, so we submit this JVM shim instead.  It launches the Python task
 * runner as a subprocess and waits for it to exit, propagating the exit code.
 *
 * All environment variables set by SparkStandaloneExecutor (including
 * AIRFLOW_EXECUTE_WORKLOAD) are inherited by the subprocess automatically.
 *
 * The Python script path is read from AIRFLOW_TASK_RUNNER_SCRIPT, defaulting
 * to /opt/airflow/scripts/airflow_task_runner.py.
 */
public class AirflowDriverLauncher {
    public static void main(String[] args) throws Exception {
        String script = System.getenv().getOrDefault(
            "AIRFLOW_TASK_RUNNER_SCRIPT",
            "/opt/airflow/scripts/airflow_task_runner.py"
        );
        System.out.println("[AirflowDriverLauncher] launching python3 " + script);
        ProcessBuilder pb = new ProcessBuilder("python3", script);
        pb.inheritIO();
        int exitCode = pb.start().waitFor();
        System.out.println("[AirflowDriverLauncher] python3 exited with code " + exitCode);
        System.exit(exitCode);
    }
}
