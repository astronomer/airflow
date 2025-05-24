use airflow_task_sdk::{registry::Registry, Task, TaskRequest, TaskResult};
use async_trait::async_trait;

struct Echo;

#[async_trait]
impl Task for Echo {
    async fn run(&self, req: TaskRequest) -> TaskResult {
        TaskResult { result: req.params }
    }
}

#[tokio::test]
async fn register_and_lookup() {
    let mut reg = Registry::new();
    reg.register_task("dag", "task", Echo);
    let task = reg.lookup_task("dag", "task").expect("task not found");
    let req = TaskRequest {
        task_id: "task".into(),
        dag_id: "dag".into(),
        run_id: "r1".into(),
        params: serde_json::json!({}),
    };
    let res = task.run(req).await;
    assert_eq!(res.result, serde_json::json!({}));
}

#[test]
#[should_panic(expected = "already registered")]
fn duplicate_panics() {
    let mut reg = Registry::new();
    reg.register_task("d", "t", Echo);
    reg.register_task("d", "t", Echo);
}

#[test]
fn lookup_missing_returns_none() {
    let reg = Registry::new();
    assert!(reg.lookup_task("d", "t").is_none());
}
