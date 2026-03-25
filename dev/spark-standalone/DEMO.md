# SparkStandaloneExecutor — Demo Script

**Runtime:** ~5 minutes
**Goal:** Show a normal `@task` function getting a live SparkSession — no `SparkSubmitOperator`, no DAG changes.

---

## Intro (~30 sec)

**Say:**
> If you want to run an Airflow task on Spark today, you have to use SparkSubmitOperator. That means a separate operator in every DAG, a standalone Python file deployed to the cluster, and a Spark connection configured by your platform team. It works — but it means every DAG author has to make infrastructure decisions.
>
> KubernetesExecutor solved this for Kubernetes: one config change, and every task runs in a pod. Nobody writes KubernetesPodOperator for every task anymore.
>
> Spark has never had that moment. This is that moment.

---

## Before You Start

Have three browser tabs open:

| Tab | URL |
|-----|-----|
| Airflow UI | http://localhost:28080 |
| Spark Master UI | http://localhost:8080 |
| MinIO Console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

---

## Step 1 — Start the cluster

```bash
cd dev/spark-standalone
docker compose up --build -d
docker compose run --rm minio-init
```

**Show:** Spark Master UI at http://localhost:8080. Two workers listed as ALIVE.

**Say:**
> We have a Spark Standalone cluster running locally in Docker — one master, two workers — and a MinIO instance for log storage.

---

## Step 2 — Start Airflow

```bash
breeze start-airflow --backend postgres --db-reset
```

**Show:** Open `files/airflow-breeze-config/spark-standalone.sh` and point to this line:

```bash
AIRFLOW__CORE__EXECUTOR=...SparkStandaloneExecutor
```

**Say:**
> This is the only change to Airflow's configuration. One line. No changes to any DAG.

---

## Step 3 — Show the DAG

Airflow UI → search `spark_word_count` → **Code** tab. Scroll to `count_words` and highlight:

```python
@task
def count_words(lines: list[str]) -> dict[str, int]:
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()  # live session — no operator needed
    ...
```

**Say:**
> This is a completely normal Python function. It calls SparkSession dot builder dot getOrCreate, and it gets back a real, live Spark session — because SparkStandaloneExecutor submits this task to the Spark cluster as a driver process. The person writing this DAG doesn't configure Spark, doesn't write a submit operator, doesn't maintain a separate application file. They just write Python.

**Show:** `prepare_text` and `report_top_words`.

**Say:**
> The other two tasks don't use Spark at all. They still run on the cluster — the executor handles that transparently.

---

## Step 4 — Trigger

Click **Trigger DAG**.

**Say:**
> Let's run it.

---

## Step 5 — Watch on the Spark UI

Switch to http://localhost:8080. Watch tasks appear under **Running Applications**:

```
airflow-spark_word_count-count_words-...    RUNNING
```

**Say:**
> Each Airflow task shows up here as a Spark application. That's count_words running on a worker right now — submitted by the executor, not by any operator in the DAG.

Wait for tasks to move to **Completed Applications**.

---

## Step 6 — View logs in Airflow

Airflow UI → click the `count_words` task box → **Logs**.

Point to:
```
Spark version : 4.0.1
Application ID: local-...
```

Scroll to the bottom:
```
────────────────────────────────────────
  Top 15 words
────────────────────────────────────────
  spark                 8  ████████████████████
  airflow               6  ███████████████
  ...
────────────────────────────────────────
```

**Say:**
> The logs come from MinIO — the Spark driver wrote them directly to the bucket, and Airflow reads them from there. No serve-logs daemon running on the worker containers.

---

## Step 7 — MinIO (optional)

http://localhost:9001 → `airflow-logs` bucket → browse to the log file.

**Say:**
> And here are the raw files in the bucket. Same content, directly accessible.

---

## Closing

**Say:**
> A normal Airflow task function. A live SparkSession. Logs stored in S3. All from one line in the config. That's SparkStandaloneExecutor.

---

## If questions come up

**Tasks that don't need Spark?**
> They still run on the cluster as driver processes — they just don't call getOrCreate. No extra configuration needed.

**Does this work with existing DAGs?**
> Yes. You get a SparkSession only if you ask for one. Existing tasks run unchanged.

**Resource overrides per task?**
> Use executor_config: `@task(executor_config={"spark_properties": {"spark.driver.memory": "2g"}})`. Any Spark property works.

**Why not just use SparkSubmitOperator?**
> You still can — it's still there. This is for teams that want Spark as the execution layer without baking it into every DAG.
