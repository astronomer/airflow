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

buildscript {
    repositories {
        mavenCentral()
    }
}

val airflowSupervisorSchemaVersion: String by project

plugins {
    kotlin("plugin.serialization") version "2.3.0"
    id("org.jsonschema2pojo") version "1.2.2"
}

// TODO: Use a hosted file instead.
val schemaInput = rootProject.file("../task-sdk/src/airflow/sdk/execution_time/schema/schema.json")
val pointersDir = layout.buildDirectory.dir("schema-pointers/main")

dependencies {
    compileOnly("com.github.spotbugs:spotbugs-annotations:4.9.8")
    compileOnly("javax.annotation:javax.annotation-api:1.3.2")

    implementation("com.fasterxml.jackson.core:jackson-annotations:2.21")
    implementation("com.fasterxml.jackson.core:jackson-core:2.21.1")
    implementation("com.fasterxml.jackson.core:jackson-databind:2.21.0")
    implementation("com.fasterxml.jackson.dataformat:jackson-dataformat-yaml:2.21.0")
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.21.0")
    implementation("com.squareup:javapoet:1.13.0")
    implementation("com.xenomachina:kotlin-argparser:2.0.7")
    implementation("io.ktor:ktor-network:3.3.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-datetime:0.7.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.10.0")
    implementation("org.msgpack:msgpack-core:0.9.11")
    implementation("org.msgpack:jackson-dataformat-msgpack:0.9.11")

    testImplementation(kotlin("test"))
    testImplementation("com.google.testing.compile:compile-testing:0.23.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}

// jsonSchema2Pojo does not accept the single JSON Schema file directly.
// It needs a list of schema files, each containing a "$ref" pointer to
// a $def. This task walks over all $ref items in the Supervisor Schema
// file and generates one JSON file with $ref for each one.
abstract class GeneratePointersTask : DefaultTask() {
    @get:InputFile
    abstract val schemaFile: RegularFileProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @TaskAction
    fun generate() {
        val srcFile = schemaFile.get().asFile
        val outDir = outputDir.get().asFile.also { it.mkdirs() }

        srcFile.copyTo(outDir.resolve(srcFile.name), overwrite = true)

        com.fasterxml.jackson.databind
            .ObjectMapper()
            .readTree(srcFile)
            .path("\$defs")
            .fieldNames()
            .forEach { type ->
                outDir
                    .resolve("$type.json")
                    .writeText("""{"${"$"}ref": "${srcFile.name}#/${"$"}defs/$type"}""" + "\n")
            }
    }
}

tasks.register<GeneratePointersTask>("generatePointers") {
    description = "Generate pointer files for jsonSchema2Pojo"
    schemaFile = layout.file(provider { schemaInput })
    outputDir = pointersDir
}

jsonSchema2Pojo {
    setSource(listOf(pointersDir.get().asFile))
    targetPackage = "org.apache.airflow.sdk.execution.api.model"
    targetDirectory =
        layout.buildDirectory
            .dir("generate-resources/main/src/main/java")
            .get()
            .asFile
    setAnnotationStyle("jackson")
    dateTimeType = "java.time.OffsetDateTime"
    includeAdditionalProperties = false
    includeConstructors = false
    generateBuilders = false
    initializeCollections = true
    includeHashcodeAndEquals = true
    includeToString = true
    useTitleAsClassname = true
    includeJsr305Annotations = true
}

sourceSets {
    main {
        java.srcDir(layout.buildDirectory.dir("generate-resources/main/src/main/java"))
    }
}

tasks.named("generateJsonSchema2Pojo") {
    dependsOn("generatePointers")
}

tasks.named("compileJava") {
    dependsOn("generateJsonSchema2Pojo")
}

tasks.named("compileKotlin") {
    dependsOn("generateJsonSchema2Pojo")
}

tasks.named("runKtlintCheckOverMainSourceSet") {
    dependsOn("generateJsonSchema2Pojo")
}

tasks.withType<Jar> {
    manifest {
        attributes(
            "Airflow-Supervisor-Schema-Version" to airflowSupervisorSchemaVersion,
        )
    }
}

tasks.withType<Test> {
    useJUnitPlatform()
}
