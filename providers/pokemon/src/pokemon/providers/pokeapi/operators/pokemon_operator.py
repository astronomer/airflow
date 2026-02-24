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

"""Operators for interacting with PokéAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from airflow.models import BaseOperator

if TYPE_CHECKING:
    from airflow.utils.context import Context


class PokemonFetchOperator(BaseOperator):
    """
    Operator to fetch Pokémon data from PokéAPI.
    
    This operator uses PokemonHook to fetch data about a specific Pokémon
    or a random Pokémon from the trainer's favorite generation.
    
    :param pokemon_name: Name or ID of the Pokémon to fetch. If not provided,
        fetches a random Pokémon from favorite generation.
    :param pokemon_conn_id: The connection ID to use.
    :param do_xcom_push: Whether to push the result to XCom.
    
    **Example**::
    
        fetch_pikachu = PokemonFetchOperator(
            task_id="fetch_pikachu",
            pokemon_name="pikachu",
            pokemon_conn_id="my_pokemon_connection",
        )
        
        fetch_random = PokemonFetchOperator(
            task_id="fetch_random",
            pokemon_conn_id="my_pokemon_connection",
        )
    """
    
    template_fields = ("pokemon_name",)
    ui_color = "#FFCB05"  # Pokémon yellow
    ui_fgcolor = "#3D7DCA"  # Pokémon blue
    
    def __init__(
        self,
        *,
        pokemon_name: str | int | None = None,
        pokemon_conn_id: str = "pokemon_default",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.pokemon_name = pokemon_name
        self.pokemon_conn_id = pokemon_conn_id
    
    def execute(self, context: Context) -> dict[str, Any]:
        """Execute the operator."""
        from pokemon.providers.pokeapi.hooks.pokemon_hook import PokemonHook
        
        hook = PokemonHook(pokemon_conn_id=self.pokemon_conn_id)
        
        if self.pokemon_name:
            self.log.info(f"🎮 Fetching Pokémon: {self.pokemon_name}")
            pokemon_data = hook.get_pokemon(self.pokemon_name)
        else:
            self.log.info("🎲 Fetching random Pokémon from favorite generation")
            pokemon_data = hook.get_random_from_favorite_generation()
        
        # Extract useful info
        result = {
            "id": pokemon_data["id"],
            "name": pokemon_data["name"],
            "types": [t["type"]["name"] for t in pokemon_data["types"]],
            "height": pokemon_data["height"],
            "weight": pokemon_data["weight"],
            "base_experience": pokemon_data["base_experience"],
            "abilities": [a["ability"]["name"] for a in pokemon_data["abilities"]],
            "stats": {
                stat["stat"]["name"]: stat["base_stat"]
                for stat in pokemon_data["stats"]
            }
        }
        
        self.log.info(f"⚡ Successfully fetched {result['name'].upper()}!")
        self.log.info(f"   Type: {', '.join(result['types'])}")
        self.log.info(f"   HP: {result['stats']['hp']}, Attack: {result['stats']['attack']}")
        
        return result
