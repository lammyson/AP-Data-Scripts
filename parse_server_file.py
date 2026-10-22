import argparse
import csv
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


class HintCsv(NamedTuple):
    """For printing hints to a CSV file to make a table similar to the Archipelago tracker page"""
    finding_player: str
    receiving_player: str
    item_name: str  # Save the item_id lookup
    location_name: str  # Save the location_id lookup
    game: str
    entrance: str


# Parse arguments
parser = argparse.ArgumentParser(
    description="Parse server .archipelago file")
parser.add_argument(
    "-f", "--input-file",
    required=True,
    type=Path,
    metavar="FILE",
    help="(Required) .archipelago file")

detailed_hints_group = parser.add_argument_group("Detailed hints options")
detailed_hints_group.add_argument(
    "--output-hints-csv",
    default=False,
    action="store_true",
    help="Output a csv file of detailed hint data")
detailed_hints_group.add_argument(
    "--output-hints-table",
    default=False,
    action="store_true",
    help="Print the detailed hints table to the terminal. NOTE: This can be giant. Recommend --output-hints-csv option")
args = parser.parse_args()

file: Path = args.input_file
print(f"Using file={file}")
# TODO - add some basic file validation

output_hints_csv: bool = args.output_hints_csv
output_hints_table: bool = args.output_hints_table
output_detailed_hints: bool = output_hints_csv or output_hints_table

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
    data: dict[Any, Any] = Utils.restricted_loads(zlib.decompress(raw_data[1:])) # pyright: ignore[reportAssignmentType]

    output_file: Path = Path(f"{file.parent}/{file.stem}.json")
    with open(output_file, 'w') as f:
        json.dump(convert_sets_to_lists(data), f, indent=3)
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

# Print a quick summary
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

print(f"Number of spheres={len(data["spheres"])}")
print(tabulate(tabular_data=table_data, headers=table_headers, tablefmt="rounded_outline"))

# Print detailed hints
if output_detailed_hints:
    hints_processed: list[HintCsv] = []
    for hint in hints:
        location = [k for k, v in data["datapackage"][data["slot_info"][hint.finding_player][1]]["location_name_to_id"].items()
                    if v == hint.location]
        item = [k for k, v in data["datapackage"][data["slot_info"][hint.receiving_player][1]]["item_name_to_id"].items()
                if v == hint.item]

        hints_processed.append(HintCsv(
            finding_player=data["slot_info"][hint.finding_player][0],
            receiving_player=data["slot_info"][hint.receiving_player][0],
            item_name=item[0],
            location_name=location[0],
            game=data["slot_info"][hint.finding_player][1],
            entrance=hint.entrance
        ))

    table_headers: list[str] = ["Finder", "Receiver", "Item", "Location", "Game", "Entrance"]
    if output_hints_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(hints_processed)
            print(f"Wrote hint table to {output_file}")

    if output_hints_table:
        print(tabulate(tabular_data=hints_processed, headers=table_headers, tablefmt="rounded_outline"))

# TODO - Show detailed start inventory items per player
# TODO - Show last sphere per player
