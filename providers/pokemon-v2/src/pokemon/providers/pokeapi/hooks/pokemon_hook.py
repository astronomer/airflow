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

"""Hook for interacting with PokéAPI."""

from __future__ import annotations

import random
from typing import Any

import requests

from airflow.hooks.base import BaseHook


class PokemonHook(BaseHook):
    """
    Hook to interact with PokéAPI (https://pokeapi.co).

    Fetches Pokémon data including stats, types, abilities, and more.

    :param pokemon_conn_id: The connection ID to use for PokéAPI.
    """

    conn_name_attr = "pokemon_conn_id"
    default_conn_name = "pokemon_default"
    conn_type = "pokemon"
    hook_name = "Pokémon"

    def __init__(self, pokemon_conn_id: str = default_conn_name) -> None:
        super().__init__()
        self.pokemon_conn_id = pokemon_conn_id
        self.api_base = "https://pokeapi.co/api/v2"

        # Get connection to retrieve trainer name and favorite generation
        try:
            conn = self.get_connection(pokemon_conn_id)
            self.trainer_name = conn.extra_dejson.get("trainer_name", "Trainer")
            self.favorite_generation = conn.extra_dejson.get("favorite_generation", "gen-i")
        except Exception:
            self.log.warning(f"Connection {pokemon_conn_id} not found, using defaults")
            self.trainer_name = "Trainer"
            self.favorite_generation = "gen-i"

    def get_pokemon(self, pokemon_name_or_id: str | int) -> dict[str, Any]:
        """
        Fetch Pokémon data by name or ID.

        :param pokemon_name_or_id: Pokémon name (e.g. 'pikachu') or ID (e.g. 25)
        :return: Dictionary containing Pokémon data
        """
        url = f"{self.api_base}/pokemon/{str(pokemon_name_or_id).lower()}"
        self.log.info(f"Fetching Pokémon data for: {pokemon_name_or_id}")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        self.log.info(
            f"✨ {self.trainer_name} caught {data['name'].title()}! "
            f"Type: {', '.join(t['type']['name'] for t in data['types'])}"
        )
        return data

    def get_generation(self, generation_id: int | str) -> dict[str, Any]:
        """
        Fetch generation data.

        :param generation_id: Generation ID (e.g. 1 or 'gen-i')
        :return: Dictionary containing generation data
        """
        url = f"{self.api_base}/generation/{str(generation_id).lower()}"
        self.log.info(f"Fetching generation data for: {generation_id}")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        return response.json()

    def get_random_from_favorite_generation(self) -> dict[str, Any]:
        """
        Get a random Pokémon from the trainer's favorite generation.

        :return: Dictionary containing random Pokémon data
        """
        self.log.info(f"Getting random Pokémon from {self.favorite_generation}")

        # Fetch generation data
        gen_data = self.get_generation(self.favorite_generation)

        # Extract Pokémon species list
        species_list = gen_data.get("pokemon_species", [])

        if not species_list:
            raise ValueError(f"No Pokémon found in {self.favorite_generation}")

        # Pick a random species
        random_species = random.choice(species_list)
        species_name = random_species["name"]

        # Fetch the actual Pokémon data
        return self.get_pokemon(species_name)

    def get_type(self, type_name: str) -> dict[str, Any]:
        """
        Fetch Pokémon type data (e.g., 'fire', 'water', 'electric').

        :param type_name: Type name
        :return: Dictionary containing type data
        """
        url = f"{self.api_base}/type/{type_name.lower()}"
        self.log.info(f"Fetching type data for: {type_name}")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        return response.json()

    def test_connection(self) -> tuple[bool, str]:
        """Test the connection to PokéAPI."""
        try:
            # Try to fetch Pikachu as a test
            self.get_pokemon("pikachu")
            return (
                True,
                f"Connection successful! Trainer: {self.trainer_name}, Fav Gen: {self.favorite_generation}",
            )
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
