use std::collections::HashMap;
use std::sync::Arc;

use crate::{Task};

/// Registry keeps a mapping of DAG and task identifiers to task implementations.
#[derive(Default)]
pub struct Registry {
    tasks: HashMap<String, HashMap<String, Arc<dyn Task>>>,
}

impl Registry {
    /// Create an empty registry.
    pub fn new() -> Self {
        Self { tasks: HashMap::new() }
    }

    /// Register a task for the given DAG and task id.
    ///
    /// Panics if a task with the same dag_id and task_id already exists.
    pub fn register_task<T>(&mut self, dag_id: &str, task_id: &str, task: T)
    where
        T: Task + 'static,
    {
        let dag = self.tasks.entry(dag_id.to_string()).or_default();
        if dag.contains_key(task_id) {
            panic!("taskId \"{}\" is already registered for DAG \"{}\"", task_id, dag_id);
        }
        dag.insert(task_id.to_string(), Arc::new(task));
    }

    /// Look up a task by dag_id and task_id.
    pub fn lookup_task(&self, dag_id: &str, task_id: &str) -> Option<Arc<dyn Task>> {
        self.tasks
            .get(dag_id)
            .and_then(|dag| dag.get(task_id).cloned())
    }
}
