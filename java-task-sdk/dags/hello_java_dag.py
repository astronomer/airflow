import os

from airflow.sdk import DAG, task
# needs task.lang to be created for other language invocations

with DAG(dag_id="hello_java_dag"):
    
    # Hello
    #
    task.lang(executor="EdgeExecutorJava", queue="java", task_id="hello") 
         


