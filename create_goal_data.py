import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass
class GoalData():
    player: str | None = None
    game: str | None = None
    goal: str | None = None
    log: str | None = None

    # Multiple pokemon games
    elite_four_requirement: str | None = None
    elite_four_count: int | None = None

    # Pokemon Emerald
    norman_requirement: str | None = None
    norman_count: int | None = None
    legendary_hunt_catch: bool | None = None
    legendary_hunt_count: int | None = None
    allowed_legendary_hunt_encounters: list[str] | None = None

    # Pokemon Crystal
    victory_road_access: str | None = None
    mt_silver_requirement: str | None = None
    mt_silver_count: int | None = None
    red_requirement: str | None = None
    red_count: int | None = None
    red_gyarados_access: str | None = None
    radio_tower_requirement: str | None = None
    radio_tower_count: int | None = None
    randomize_pokedex: str | None = None

class PokemonEmerald():
    @staticmethod
    def ParseGoalData(slot: dict[str, Any], goal: GoalData):
        goal.goal = PokemonEmerald.goal_to_string(slot["slot_data"]["goal"])
        match goal.goal:
            case "champion" | "steven":
                goal.elite_four_requirement = PokemonEmerald.requirement_to_string(slot["slot_data"]["elite_four_requirement"])
                goal.elite_four_count = slot["slot_data"]["elite_four_count"]
            case "norman":
                goal.norman_requirement = PokemonEmerald.requirement_to_string(slot["slot_data"]["norman_requirement"])
                goal.norman_count = slot["slot_data"]["norman_count"]
            case "legendary_hunt":
                goal.legendary_hunt_catch = slot["slot_data"]["legendary_hunt_catch"] == 1
                goal.legendary_hunt_count = slot["slot_data"]["legendary_hunt_count"]
                goal.allowed_legendary_hunt_encounters = slot["slot_data"]["allowed_legendary_hunt_encounters"]
        return goal

    @staticmethod
    def goal_to_string(goal: int):
        match goal:
            case 0: return "champion"
            case 1: return "steven"
            case 2: return "norman"
            case 3: return "legendary_hunt"
            case _: return "Unknown goal"

    @staticmethod
    def requirement_to_string(requirement: int):
        match requirement:
            case 0: return "badges"
            case 1: return "gyms"
            case _: return "Unknown requirement"


class PokemonCrystal():
    @staticmethod
    def ParseGoalData(slot: dict[str, Any], goal: GoalData):
        goal.goal = PokemonCrystal.goal_to_string(slot["slot_data"]["goal"])
        match goal.goal:
            case "elite_four":
                goal.victory_road_access = PokemonCrystal.victory_road_access_to_string(slot["slot_data"]["victory_road_access"])
                goal.elite_four_requirement = PokemonCrystal.elite_four_requirement_to_string(slot["slot_data"]["elite_four_requirement"])
                goal.elite_four_count = slot["slot_data"]["elite_four_count"]
            case "red":
                goal.mt_silver_requirement = PokemonCrystal.requirement_to_string(slot["slot_data"]["mt_silver_requirement"])
                goal.mt_silver_count = slot["slot_data"]["mt_silver_count"]
                goal.red_requirement = PokemonCrystal.requirement_to_string(slot["slot_data"]["red_requirement"])
                goal.red_count = slot["slot_data"]["red_count"]
            case "diploma":
                goal.randomize_pokedex = PokemonCrystal.randomize_pokedex_to_string(slot["slot_data"]["randomize_pokedex"])
            case "rival":
                goal.victory_road_access = PokemonCrystal.victory_road_access_to_string(slot["slot_data"]["victory_road_access"])
                goal.elite_four_requirement = PokemonCrystal.elite_four_requirement_to_string(slot["slot_data"]["elite_four_requirement"])
                goal.elite_four_count = slot["slot_data"]["elite_four_count"]
            case "defeat_team_rocket":
                goal.red_gyarados_access = PokemonCrystal.red_gyarados_access_to_string(slot["slot_data"]["red_gyarados_access"])
                goal.radio_tower_requirement = PokemonCrystal.requirement_to_string(slot["slot_data"]["radio_tower_requirement"])
                goal.radio_tower_count = slot["slot_data"]["radio_tower_count"]
            case "unown_hunt":
                pass
        return goal

    @staticmethod
    def goal_to_string(goal: int):
        match goal:
            case 0: return "elite_four"
            case 1: return "red"
            case 2: return "diploma"
            case 3: return "rival"
            case 4: return "defeat_team_rocket"
            case 5: return "unown_hunt"
            case _: return "Unknown goal"

    @staticmethod
    def requirement_to_string(requirement: int):
        match requirement:
            case 0: return "badges"
            case 1: return "gyms"
            case _: return "Unknown requirement"

    @staticmethod
    def elite_four_requirement_to_string(requirement: int):
        match requirement:
            case 0: return "badges"
            case 1: return "gyms"
            case 2: return "johto_badges"
            case _: return "Unknown elite_four_requirement"

    @staticmethod
    def victory_road_access_to_string(victory_road_access: int):
        match victory_road_access:
            case 0: return "vanilla"
            case 1: return "strength"
            case _: return "Unknown victory_road_access"

    @staticmethod
    def red_gyarados_access_to_string(red_gyarados_access: int):
        match red_gyarados_access:
            case 0: return "vanilla"
            case 1: return "whirlpool"
            case 2: return "shore"
            case _: return "Unknown randomize_pokedex"

    @staticmethod
    def randomize_pokedex_to_string(randomize_pokedex: int):
        match randomize_pokedex:
            case 0: return "vanilla"
            case 1: return "start_with"
            case 2: return "randomize"
            case _: return "Unknown randomize_pokedex"

def main():
    parser = argparse.ArgumentParser(description="Output goal data in a more human readable format. Requires the room data from get-room-data.py")
    parser.add_argument(
        "-f", "--data-folder",
        required=True,
        type=Path,
        metavar="FOLDER",
        help="(Required) Folder containing room data retrieved by get_room_data.py")
    args = parser.parse_args()

    if not args.data_folder.exists():
        parser.error(f"Data folder={args.data_folder} does not exist")
    if not Path(args.data_folder).is_dir():
        parser.error(f"Data folder={args.data_folder} is not a directory")

    data_folder: str = args.data_folder
    with open(f"{data_folder}/room_status.json", "r") as file:
        room_status: dict[str, Any] = json.load(file)
    with open(f"{data_folder}/slot_data_tracker.json", "r") as file:
        slot_data: list[dict[str, Any]] = json.load(file)

    # Go through each slot and parse the relevant goal data for each game
    goal_data: list[GoalData] = []
    for slot in slot_data:
        goal: GoalData = GoalData()
        goal.player = room_status["players"][slot["player"]-1][0]
        goal.game = room_status["players"][slot["player"]-1][1]

        match goal.game:
            case "Pokemon Emerald":
                PokemonEmerald.ParseGoalData(slot=slot, goal=goal)
            case "Pokemon Crystal":
                PokemonCrystal.ParseGoalData(slot=slot, goal=goal)
            case _:
                goal.log = f"Unsupported game {goal.game}"

        goal_data.append(goal)

    # Remove all empty or None fields and convert to list[dict[str,Any]]
    goal_data_list_filtered = [
        {k: v for k, v in asdict(d).items() if v is not None and v != "" and v != [] and v != {}}
        for d in goal_data
    ]

    with open(f"{data_folder}/goal_data.json", "w") as file:
        json.dump(goal_data_list_filtered, file, indent=3)
    print(f"Saved goal data to to {data_folder}/goal_data.json")

if __name__ == "__main__":
    main()
