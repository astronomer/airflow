use async_trait::async_trait;
use serde::{Deserialize, Serialize};

/// Request sent from Airflow containing task execution info.
#[derive(Debug, Serialize, Deserialize)]
pub struct TaskRequest {
    /// Identifier of the task within the DAG
    pub task_id: String,
    /// Identifier of the DAG this task belongs to
    pub dag_id: String,
    /// Run id of the DAG run
    pub run_id: String,
    /// Arbitrary parameters provided for the task
    #[serde(default)]
    pub params: serde_json::Value,
}

/// Result returned by a task execution.
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub struct TaskResult {
    /// Optional JSON value returned by the task
    #[serde(default)]
    pub result: serde_json::Value,
}

/// Async trait implemented by user tasks.
#[async_trait]
pub trait Task: Send + Sync {
    async fn run(&self, request: TaskRequest) -> TaskResult;
}

/// Execute a task and return its result.
pub async fn execute<T: Task>(task: T, request: TaskRequest) -> TaskResult {
    task.run(request).await
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
