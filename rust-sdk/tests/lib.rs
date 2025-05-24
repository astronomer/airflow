use airflow_task_sdk::{execute, Task, TaskRequest, TaskResult};
use async_trait::async_trait;

struct Echo;

#[async_trait]
impl Task for Echo {
    async fn run(&self, request: TaskRequest) -> TaskResult {
        TaskResult {
            result: request.params,
        }
    }
}

#[tokio::test]
async fn test_execute() {
    let req = TaskRequest {
        task_id: "t1".into(),
        dag_id: "d1".into(),
        run_id: "r1".into(),
        params: serde_json::json!({"a": 1}),
    };
    let res = execute(Echo, req).await;
    assert_eq!(res.result, serde_json::json!({"a": 1}));
}
