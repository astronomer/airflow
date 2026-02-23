<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
 -->

# Remote Execution POC with Docker Compose

This docker-compose setup demonstrates Worker Provider Discovery with physically separate environments:

- **Control Plane** (scheduler, API, dag-processor, triggerer): Minimal providers (only celery)
- **Worker**: Full provider packages (99+)

## Setup

### 1. Build Control Plane Image

```bash
cd /Users/amoghdesai/Documents/OSS/repos/airflow
docker build -f Dockerfile.control-plane -t airflow-control-plane:latest .
```

### 2. Start All Services

```bash
cd airflow-core/docs/howto/docker-compose/
docker-compose -f docker-compose-remote-exec.yaml up
```

## What to Look For

### Worker Logs
```bash
docker-compose -f docker-compose-remote-exec.yaml logs -f airflow-worker
```

Look for:
- ✅ `[RegisterWorkerProviders] Processing registration`
- ✅ `Discovered 99 installed providers`
- ✅ `Successfully registered 99 providers`

### API Server Logs
```bash
docker-compose -f docker-compose-remote-exec.yaml logs -f airflow-apiserver
```

Look for:
- ✅ `Received provider registration from worker celery@... with 99 providers`
- ✅ `Successfully registered 99 providers`
- ✅ `POST /execution/worker/register-providers HTTP/1.1" 200`

### Scheduler Logs
```bash
docker-compose -f docker-compose-remote-exec.yaml logs -f airflow-scheduler
```

Look for:
- ✅ `Discovered 1 active Celery workers`
- ✅ `Dispatched provider registration to worker`

## Verification

### Check Provider Counts

**Control plane (should have ~1 provider - only celery):**
```bash
docker-compose -f docker-compose-remote-exec.yaml exec airflow-scheduler pip list | grep apache-airflow-providers
```

**Worker (should have ~99 providers):**
```bash
docker-compose -f docker-compose-remote-exec.yaml exec airflow-worker pip list | grep apache-airflow-providers | wc -l
```

## Access UI

Open http://localhost:8080
- Username: `airflow`
- Password: `airflow`

## Cleanup

```bash
docker-compose -f docker-compose-remote-exec.yaml down -v
```

## What This Proves

**Control plane with minimal providers receives full provider inventory from workers**, demonstrating:
- ✅ Remote execution architecture
- ✅ Worker self-reporting
- ✅ API server as central provider registry
- ✅ No need for providers on control plane
