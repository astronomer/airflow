import os

from airflow.sdk import DAG, task
# needs task.lang to be created for other language invocations

with DAG(dag_id="tutorial_java_dag"):
    
    # Extract
    #
    task.lang(executor="EdgeExecutorJava", queue="java", task_id="extract") 


    # Transform 
    #
    task.lang(executor="EdgeExecutorJava", queue="java", task_id="transform") 

    # Load
    #
    task.lang(executor="EdgeExecutorJava", queue="java", task_id="load") 



