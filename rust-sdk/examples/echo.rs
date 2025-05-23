use airflow_task_sdk::{execute, Task, TaskRequest, TaskResult};
use async_trait::async_trait;

struct Echo;

#[async_trait]
impl Task for Echo {
    async fn run(&self, req: TaskRequest) -> TaskResult {
        TaskResult { result: req.params }
    }
}

#[tokio::main]
async fn main() {
    let req = TaskRequest {
        task_id: "echo".into(),
        dag_id: "example".into(),
        run_id: "run1".into(),
        params: serde_json::json!({"hello": "airflow"}),
    };
    let result = execute(Echo, req).await;
    println!("result: {:?}", result);
}
