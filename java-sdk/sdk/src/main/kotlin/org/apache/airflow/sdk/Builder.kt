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

@file:Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")

package org.apache.airflow.sdk

import com.squareup.javapoet.ClassName
import com.squareup.javapoet.JavaFile
import com.squareup.javapoet.MethodSpec
import com.squareup.javapoet.TypeName
import com.squareup.javapoet.TypeSpec
import javax.annotation.processing.AbstractProcessor
import javax.annotation.processing.ProcessingEnvironment
import javax.annotation.processing.RoundEnvironment
import javax.annotation.processing.SupportedAnnotationTypes
import javax.annotation.processing.SupportedSourceVersion
import javax.lang.model.SourceVersion
import javax.lang.model.element.ExecutableElement
import javax.lang.model.element.Modifier
import javax.lang.model.element.TypeElement
import javax.lang.model.type.TypeKind
import javax.lang.model.type.TypeMirror
import javax.tools.Diagnostic
import java.util.List as JavaList

/**
 * Annotation to automate a Dag-builder pattern.
 *
 * When applied on a class Foo, this generates a FooBuilder class with a static build method
 * to create the Dag structure automatically.
 *
 * @param id Override the Dag ID. If empty or not provided, the annotated class's name is used by default.
 */
@Target(AnnotationTarget.CLASS)
@MustBeDocumented
annotation class DagBuilder(
  val id: String = "",
) {
  /**
   * Annotation to automate task definition in a Dag-builder pattern.
   *
   * @param id Override the task ID. If empty or not provided, the annotated function's name is used by default.
   * @param depends List of task IDs this task depends on.
   */
  @Target(AnnotationTarget.FUNCTION)
  @MustBeDocumented
  annotation class Task(
    val id: String = "",
    val depends: Array<String> = [],
  )

  /**
   * Annotation to mark a method parameter as an XCom input.
   */
  @Target(AnnotationTarget.VALUE_PARAMETER)
  @MustBeDocumented
  annotation class XCom(
    val task: String,
    val key: String = Client.XCOM_RETURN_KEY,
  )
}

@SupportedAnnotationTypes("org.apache.airflow.sdk.DagBuilder")
@SupportedSourceVersion(SourceVersion.RELEASE_11)
class DagBuilderProcessor : AbstractProcessor() {
  override fun process(
    annotations: Set<TypeElement>,
    roundEnv: RoundEnvironment,
  ): Boolean {
    if (annotations.isEmpty()) return false
    roundEnv.getElementsAnnotatedWith(DagBuilder::class.java).filterIsInstance<TypeElement>().forEach { el ->
      runCatching { generateDagBuilder(el) }.onFailure { e ->
        processingEnv.messager.printMessage(
          Diagnostic.Kind.ERROR,
          e.message ?: "Unknown error",
          el,
        )
      }
    }
    return true
  }

  private fun generateDagBuilder(el: TypeElement) {
    val dagId = el.getAnnotation(DagBuilder::class.java)!!.id.ifBlank { el.simpleName.toString() }

    val builderClass =
      TypeSpec
        .classBuilder("${el.simpleName}Builder")
        .addModifiers(Modifier.PUBLIC, Modifier.FINAL)

    val buildMethod =
      MethodSpec
        .methodBuilder("build")
        .addModifiers(Modifier.PUBLIC, Modifier.STATIC)
        .returns(ClassName.get(Dag::class.java))
        .addStatement($$"var dag = new $T($S)", ClassName.get(Dag::class.java), dagId)

    for (inner in el.enclosedElements) {
      if (inner !is ExecutableElement) continue
      if (inner.isVarArgs) throw IllegalArgumentException("Cannot create task from vararg function ${inner.simpleName}")

      val ann = inner.getAnnotation(DagBuilder.Task::class.java) ?: continue
      val innerName = inner.simpleName.toString().replaceFirstChar(Char::uppercase)
      val dependsPlaceholder = ann.depends.joinToString { $$"$S" }

      builderClass.addType(generateTask(innerName, inner, el))
      buildMethod.addStatement(
        $$"dag.addTask($S, $L.class, $L.of($${dependsPlaceholder}))",
        ann.id.ifBlank { inner.simpleName.toString() },
        innerName,
        ClassName.get(JavaList::class.java),
        *ann.depends,
      )
    }

    buildMethod.addStatement("return dag")
    builderClass.addMethod(buildMethod.build())

    JavaFile
      .builder(
        processingEnv.elementUtils
          .getPackageOf(el)
          .qualifiedName
          .toString(),
        builderClass.build(),
      ).build()
      .writeTo(processingEnv.filer)
  }

  private fun generateTask(
    name: String,
    inner: ExecutableElement,
    parent: TypeElement,
  ): TypeSpec {
    val clientType = ClassName.get(Client::class.java)
    val contextType = ClassName.get(Context::class.java)

    val executeSpec =
      MethodSpec
        .methodBuilder("execute")
        .addAnnotation(Override::class.java)
        .addModifiers(Modifier.PUBLIC)
        .returns(TypeName.VOID)
        .addParameter(contextType, "context")
        .addParameter(clientType, "client")
        .addException(Exception::class.java)

    val required = mutableListOf<RequiredXCom>()
    val innerArgs =
      with(processingEnv) {
        inner.parameters.joinToString { param ->
          val anno = param.getAnnotation(DagBuilder.XCom::class.java)
          val type = param.asType()
          when {
            anno != null ->
              param.simpleName.toString().also {
                required += RequiredXCom(type, it, anno.task.ifBlank { it })
              }
            isType(type, clientType) -> "client"
            isType(type, contextType) -> "context"
            else -> throw IllegalArgumentException("Unsupported parameter type: $type")
          }
        }
      }
    required.forEach {
      executeSpec.addStatement(
        $$"var $L = ($T) client.getXCom($S)",
        it.paramName,
        with(TypeName.get(it.paramType)) { if (isPrimitive) box() else this },
        it.taskId,
      )
    }
    if (inner.returnType.kind == TypeKind.VOID) {
      $$"new $T().$L($L)"
    } else {
      $$"client.setXCom(new $T().$L($L))"
    }.also {
      executeSpec.addStatement(
        it,
        ClassName.get(parent),
        inner.simpleName,
        innerArgs,
      )
    }

    return TypeSpec
      .classBuilder(name)
      .addSuperinterface(Task::class.java)
      .addModifiers(Modifier.PUBLIC, Modifier.FINAL, Modifier.STATIC)
      .addMethod(executeSpec.build())
      .build()
  }
}

private fun ProcessingEnvironment.isType(
  t: TypeMirror,
  c: ClassName,
): Boolean = typeUtils.isSameType(t, elementUtils.getTypeElement(c.canonicalName()).asType())

private data class RequiredXCom(
  val paramType: TypeMirror,
  val paramName: String,
  val taskId: String,
)
