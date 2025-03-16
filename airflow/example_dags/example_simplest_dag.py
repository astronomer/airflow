from airflow.decorators import dag, task


@dag
def example_simplest_dag():
    @task
    def my_task():
        pass

    my_task()


example_simplest_dag()
