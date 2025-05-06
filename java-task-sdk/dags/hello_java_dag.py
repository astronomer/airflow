import os

from airflow.sdk import DAG, task
# needs task.remote to be created

with DAG(dag_id="hello_java_dag"):
    
    # Hello
    #
    task.remote(executor="EdgeExecutorJava", queue="java", task_id="hello") 
         


