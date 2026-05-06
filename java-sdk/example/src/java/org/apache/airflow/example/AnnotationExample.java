/*
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

package org.apache.airflow.example;

import org.apache.airflow.sdk.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@DagBuilder(id = "java_annotation_example")
public class AnnotationExample {
  private static final Logger logger = LoggerFactory.getLogger(AnnotationExample.class);

  @DagBuilder.Task(id = "extract")
  public void extractValue(Client client) {
    logger.info("Hello from task");
    var connection = client.getConnection("test_http");
    logger.info("Got con {}", connection);
  }

  @DagBuilder.Task(id = "transform", depends = {"extract"})
  public void transformValue() {
    logger.info("Transforming...");
  }

  @DagBuilder.Task(depends = {"transform"})
  public void load() {
    logger.info("Done!");
  }
}
