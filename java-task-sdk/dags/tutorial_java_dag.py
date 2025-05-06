import os

from airflow.sdk import DAG, task

with DAG(dag_id="tutorial_java_dag"):
    
    # Extract
    #
    task.remote(executor="EdgeExecutorJava", queue="java", task_id="extract") 


    # Transform 
    #
    task.remote(executor="EdgeExecutorJava", queue="java", task_id="transform") 

    # Load
    #
    task.remote(executor="EdgeExecutorJava", queue="java", task_id="load") 



