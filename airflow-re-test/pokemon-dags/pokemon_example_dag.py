# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Example DAG using the Pokémon Provider.

This DAG demonstrates fetching Pokémon data using the custom
pokemon-airflow-provider package.
"""

from __future__ import annotations

from datetime import datetime

from airflow.sdk import DAG
from pokemon.providers.pokeapi.operators.pokemon_operator import PokemonFetchOperator

with DAG(
    dag_id="pokemon_data_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["pokemon", "example", "custom-provider"],
    doc_md="""
    # Pokémon Data Pipeline 🎮⚡
    
    This DAG fetches Pokémon data from PokéAPI using the custom Pokémon provider.
    
    ## Tasks:
    - **fetch_pikachu**: Fetches data about Pikachu
    - **fetch_charizard**: Fetches data about Charizard
    - **fetch_mew**: Fetches data about Mew
    - **fetch_random**: Fetches a random Pokémon from favorite generation
    
    ## Setup:
    Create a connection with:
    - Connection ID: `pokemon_default`
    - Connection Type: `Pokémon`
    - Trainer Name: Your name
    - Favorite Generation: gen-i, gen-ii, etc.
    """,
) as dag:
    # Fetch specific Pokémon
    fetch_pikachu = PokemonFetchOperator(
        task_id="fetch_pikachu",
        pokemon_name="pikachu",
        pokemon_conn_id="pokemon_default",
    )

    fetch_charizard = PokemonFetchOperator(
        task_id="fetch_charizard",
        pokemon_name="charizard",
        pokemon_conn_id="pokemon_default",
    )

    fetch_mew = PokemonFetchOperator(
        task_id="fetch_mew",
        pokemon_name="mew",
        pokemon_conn_id="pokemon_default",
    )

    # Fetch random Pokémon from favorite generation
    fetch_random = PokemonFetchOperator(
        task_id="fetch_random_from_fav_gen",
        pokemon_conn_id="pokemon_default",
    )

    # Define task dependencies
    [fetch_pikachu, fetch_charizard, fetch_mew] >> fetch_random
