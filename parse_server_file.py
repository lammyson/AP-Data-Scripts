import argparse
import json
from pathlib import Path
import sys
from tabulate import tabulate, SEPARATING_LINE
from typing import Any, NamedTuple
import warnings
import zlib


def convert_sets_to_lists(obj: dict | list | set) -> dict[Any, Any] | list[Any]:
    """Recursively converts sets to lists inside a dict or list"""
    if isinstance(obj, dict):
        return {key: convert_sets_to_lists(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(item) for item in obj]
    elif isinstance(obj, set):
        return [convert_sets_to_lists(item) for item in obj]
    return obj


class SummaryTableRow(NamedTuple):
    id: int
    name: str
    game: str
    num_hints_finder: int
    num_hints_receiver: int
    num_start_inventory: int


# Parse arguments
parser = argparse.ArgumentParser(
    description="Parse server .archipelago file")
parser.add_argument(
    "-f", "--input-file",
    required=True,
    type=Path,
    metavar="FILE",
    help="(Required) .archipelago file")
args = parser.parse_args()

file: Path = args.input_file
print(f"Using file={file}")
# TODO - add some basic file validation

with open(file, 'rb') as f:
    raw_data = f.read()

# Load the .archipelago file
with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    script_dir = Path(__file__).resolve().parent
    sys.path.append(f"{script_dir}/Archipelago")
    from Archipelago import Utils
    from Archipelago.NetUtils import Hint, HintStatus

    format_version = raw_data[0]
    if format_version > 3:
        raise Utils.VersionException("Incompatible multidata.")
    data: dict[Any, Any] = convert_sets_to_lists(Utils.restricted_loads(zlib.decompress(raw_data[1:]))) # pyright: ignore[reportAssignmentType]

    output_file: Path = Path(f"{file.parent}/{file.stem}.json")
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=3)
        print(f"Saved human readable version of server file to {output_file}")

num_players: int = len(data["slot_info"])

num_start_inventory: int = 0
for player, items in data["precollected_items"].items():
    num_start_inventory += len(items)

# Process hints
num_start_hints_finder: list[int] = [0] * (num_players+1)
num_start_hints_receiver: list[int] = [0] * (num_players+1)
hints: list[Hint] = []
for slot, player_hints in data["precollected_hints"].items():
    for raw_hint in player_hints:
        hint: Hint = Hint(*raw_hint)
        if hint not in hints:
            hints.append(hint)
            num_start_hints_finder[hint.finding_player] += 1
            num_start_hints_receiver[hint.receiving_player] += 1

# Create the table data
table_headers = ["id", "Name", "Game", "Start Hints - Finder", "Start Hints - Receiver", "Start Inventory"]
table_data: list = []
for slot, player in data["slot_info"].items():
    slot_num: int = int(slot)
    table_data.append(SummaryTableRow(
        id=slot_num,
        name=player[0],
        game=player[1],
        num_hints_finder=num_start_hints_finder[slot_num],
        num_hints_receiver=num_start_hints_receiver[slot_num],
        num_start_inventory=len(data["precollected_items"][slot])
    ))
table_data.append(SEPARATING_LINE)
table_data.append(["", "", "Totals", sum(num_start_hints_finder), sum(num_start_hints_receiver), num_start_inventory])

# TODO - Show detailed hints - at least the datapackage is there already
# TODO - Show detailed start inventory items per player
print(f"Number of spheres={len(data["spheres"])}")
# TODO - Show last sphere per player

print(tabulate(tabular_data=table_data, headers=table_headers, tablefmt="rounded_outline"))
