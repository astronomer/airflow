use airflow_task_sdk::{execute, Task, TaskRequest, TaskResult};
use async_trait::async_trait;
use celery::prelude::*;
use clap::Parser;

/// Simple echo task used by the worker example.
struct Echo;

#[async_trait]
impl Task for Echo {
    async fn run(&self, req: TaskRequest) -> TaskResult {
        TaskResult { result: req.params }
    }
}

#[derive(Parser, Debug)]
struct Args {
    /// Redis broker URL, e.g. redis://localhost:6379/0
    #[clap(long)]
    broker: String,
    /// Celery queue to listen on
    #[clap(long, default_value = "default")]
    queue: String,
}

#[celery::task]
async fn execute_workload(payload: String) -> CeleryResult<()> {
    let req: TaskRequest = serde_json::from_str(&payload)?;
    let result = execute(Echo, req).await;
    println!("task result: {:?}", result);
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let app = celery::app!(
        broker = RedisBroker { args.broker.as_str() },
        tasks = [execute_workload],
    )?;
    app.worker().with_queue(&args.queue).consume().await?;
    Ok(())
}
