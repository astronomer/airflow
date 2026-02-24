# Pokémon Airflow Provider 🎮⚡

> **Gotta orchestrate 'em all!**

A custom Airflow provider for fetching and orchestrating Pokémon data using [PokéAPI](https://pokeapi.co/).

## Features

- 🎯 **Custom Connection Type** - Define your trainer name and favorite generation
- ⚡ **PokémonHook** - Interact with PokéAPI
- 🎮 **PokémonFetchOperator** - Fetch specific or random Pokémon
- 🔧 **Easy Integration** - Works seamlessly with Airflow 3.0+

## Installation

### Build the Provider

```bash
cd providers/pokemon
python -m build
```

This creates a wheel file in `dist/`:
```
dist/pokemon_airflow_provider-1.0.0-py3-none-any.whl
```

### Install on Worker

#### Option 1: Install in Running Container

```bash
# Copy wheel to worker container
docker cp dist/pokemon_airflow_provider-1.0.0-py3-none-any.whl \
  airflow-re-test-airflow-worker-1:/tmp/

# Install in worker
docker exec airflow-re-test-airflow-worker-1 \
  pip install /tmp/pokemon_airflow_provider-1.0.0-py3-none-any.whl

# Restart worker to register provider
cd ../../airflow-re-test
docker compose restart airflow-worker
```

#### Option 2: Custom Worker Dockerfile

Create a custom worker image that includes the provider:

```dockerfile
FROM ghcr.io/apache/airflow/main/ci/python3.10:latest

COPY dist/pokemon_airflow_provider-1.0.0-py3-none-any.whl /tmp/
RUN pip install /tmp/pokemon_airflow_provider-1.0.0-py3-none-any.whl
```

## Usage

### 1. Create a Connection

In the Airflow UI, go to **Admin → Connections** and create a new connection:

- **Connection ID**: `my_pokemon_connection`
- **Connection Type**: `Pokémon`
- **Trainer Name**: `Ash Ketchum`
- **Favorite Generation**: `gen-i`

### 2. Use in DAG

```python
from airflow.sdk import DAG
from datetime import datetime
from pokemon.providers.pokeapi.operators.pokemon_operator import PokemonFetchOperator

with DAG(
    dag_id="pokemon_example",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
) as dag:
    
    # Fetch a specific Pokémon
    fetch_pikachu = PokemonFetchOperator(
        task_id="fetch_pikachu",
        pokemon_name="pikachu",
        pokemon_conn_id="my_pokemon_connection",
    )
    
    # Fetch a random Pokémon from your favorite generation
    fetch_random = PokemonFetchOperator(
        task_id="fetch_random_gen1",
        pokemon_conn_id="my_pokemon_connection",
    )
    
    fetch_pikachu >> fetch_random
```

## Verification

### Check Provider Registration

After installing and restarting the worker, check the logs:

```bash
docker logs airflow-re-test-airflow-worker-1 | grep -i pokemon
```

You should see:
```
Successfully registered 1 providers for worker celery@...
```

### Verify in UI

1. **Providers Page** (`http://localhost:8080/providers`):
   - Provider name: `pokemon-airflow-provider`
   - Version: `1.0.0`
   - Source: **Custom** (purple badge)
   - Workers: `celery@...`

2. **Connections Page** (`http://localhost:8080/ui/connections/hook_meta`):
   - Connection type: `pokemon`
   - Fields: Trainer Name, Favorite Generation

## Provider Details

- **Package Name**: `pokemon-airflow-provider` (custom, not Apache)
- **Version**: 1.0.0
- **Connection Type**: `pokemon`
- **Hook**: `PokemonHook`
- **Operators**: `PokemonFetchOperator`

## Upgrading

To upgrade to version 2.0.0 (with additional fields):

1. Update `version` in `pyproject.toml`
2. Add new fields to `provider.yaml`
3. Rebuild: `python -m build`
4. Reinstall on worker
5. Restart worker

The new connection fields will automatically appear in the UI!

## License

Apache License 2.0
