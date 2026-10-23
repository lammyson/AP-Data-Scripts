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
    item_name: str
    location_name: str
    finding_game: str
    receiving_game: str
    entrance: str


class InventoryCsv(NamedTuple):
    """For printing start inventory to a CSV file"""
    player: str
    game: str
    item_name: str
    item_amount: int


# Parse arguments
parser = argparse.ArgumentParser(
    description="Parse server .archipelago file")
parser.add_argument(
    "-f", "--input-file",
    required=True,
    type=Path,
    metavar="FILE",
    help="(Required) .archipelago file")
parser.add_argument(
    "-d", "--debug",
    default=False,
    action="store_true",
    help="Print debug statements and files")

detailed_start_hints_group = parser.add_argument_group("Detailed start hints options")
detailed_start_hints_group.add_argument(
    "--output-hints-csv",
    default=False,
    action="store_true",
    help="Output a csv file of the detailed start hints")
detailed_start_hints_group.add_argument(
    "--output-hints-table",
    default=False,
    action="store_true",
    help="Print the detailed start hints to the terminal as a table. "
         "NOTE: This can be giant. Recommend --output-hints-csv option")

detailed_start_inventory_group = parser.add_argument_group("Detailed start inventory options")
detailed_start_inventory_group.add_argument(
    "--output-inventory-csv",
    default=False,
    action="store_true",
    help="Output a csv file of the detailed start inventory items")
detailed_start_inventory_group.add_argument(
    "--output-inventory-table",
    default=False,
    action="store_true",
    help="Print the detailed start inventory items to the terminal as a table. "
         "NOTE: This can be giant. Recommend --output-inventory-csv option")
args = parser.parse_args()

debug: bool = args.debug

file: Path = args.input_file
print(f"Using file={file}")
# TODO - add some basic file validation

output_hints_csv: bool = args.output_hints_csv
output_hints_table: bool = args.output_hints_table
output_detailed_hints: bool = output_hints_csv or output_hints_table

output_inventory_csv: bool = args.output_inventory_csv
output_inventory_table: bool = args.output_inventory_table
output_detailed_inventory: bool = output_inventory_csv or output_inventory_table

with open(file, 'rb') as f:
    raw_data = f.read()

# Load the .archipelago file
with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    script_dir = Path(__file__).resolve().parent
    sys.path.append(f"{script_dir}/Archipelago")
    from Archipelago import Utils
    from Archipelago.NetUtils import Hint, MultiData

    format_version = raw_data[0]
    if format_version > 3:
        raise Utils.VersionException("Incompatible multidata.")
    multidata: MultiData = Utils.restricted_loads(zlib.decompress(raw_data[1:]))

    if debug:
        output_file: Path = Path(f"{file.parent}/{file.stem}.json")
        with open(output_file, 'w') as f:
            json.dump(convert_sets_to_lists(multidata), f, indent=2)
            print(f"Saved human readable version of server file to {output_file}")

num_players: int = len(multidata["slot_info"])

num_start_inventory: int = 0
for player, items in multidata["precollected_items"].items():
    num_start_inventory += len(items)

# Process hints
num_start_hints_finder: list[int] = [0] * (num_players+1)
num_start_hints_receiver: list[int] = [0] * (num_players+1)
hints: set[Hint] = set([])
for player_hints in multidata["precollected_hints"].values():
    for hint in player_hints:
        if hint not in hints:
            hints.add(hint)
            num_start_hints_finder[hint.finding_player] += 1
            num_start_hints_receiver[hint.receiving_player] += 1

# Print a quick summary
table_headers = ["id", "Name", "Game", "Start Hints - Finder", "Start Hints - Receiver", "Start Inventory"]
table_data: list = []
for slot_id, player in multidata["slot_info"].items():
    table_data.append(SummaryTableRow(
        id=slot_id,
        name=player.name,
        game=player.game,
        num_hints_finder=num_start_hints_finder[slot_id],
        num_hints_receiver=num_start_hints_receiver[slot_id],
        num_start_inventory=len(multidata["precollected_items"][slot_id])
    ))
table_data.append(SEPARATING_LINE)
table_data.append(["", "", "Totals", sum(num_start_hints_finder), sum(num_start_hints_receiver), num_start_inventory])

print(f"\nNumber of spheres={len(multidata["spheres"])}")
print(tabulate(tabular_data=table_data, headers=table_headers, tablefmt="rounded_outline"))

# Print detailed hints
if output_detailed_hints:
    hints_processed: list[HintCsv] = []
    for hint in hints:
        finding_slot = multidata["slot_info"][hint.finding_player]
        receiving_slot = multidata["slot_info"][hint.receiving_player]
        finding_datapackage = multidata["datapackage"][finding_slot.game].get("location_name_to_id")
        receiving_datapackage = multidata["datapackage"][receiving_slot.game].get("item_name_to_id")
        if finding_datapackage is None:
            raise KeyError(f"Unable to get location_name_to_id dict for game='{finding_slot.game}'")
        if receiving_datapackage is None:
            raise KeyError(f"Unable to get item_name_to_id dict for game='{receiving_slot.game}'")

        location = [k for k, v in finding_datapackage.items() if v == hint.location]
        item = [k for k, v in receiving_datapackage.items() if v == hint.item]
        hints_processed.append(HintCsv(
            finding_player=finding_slot.name,
            receiving_player=receiving_slot.name,
            item_name=item[0],
            location_name=location[0],
            finding_game=finding_slot.game,
            receiving_game=receiving_slot.game,
            entrance=hint.entrance
        ))

    table_headers: list[str] = ["Finder", "Receiver", "Item", "Location", "Finding Game", "Receiving Game", "Entrance"]
    if output_hints_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}_start_hints.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(hints_processed)
            print(f"\nWrote detailed start hints table to {output_file}")

    if output_hints_table:
        print("\nDetailed start hints table")
        print(tabulate(tabular_data=hints_processed, headers=table_headers, tablefmt="rounded_outline"))

# TODO - Show detailed start inventory items per player
# Print detailed start inventory
if output_detailed_inventory:
    inventory: list[InventoryCsv] = []
    for player_id, item_ids in multidata["precollected_items"].items():
        slot = multidata["slot_info"][player_id]
        datapackage = multidata["datapackage"][slot.game].get("item_name_to_id")
        if datapackage is None:
            raise KeyError(f"Unable to get item_name_to_id dict for game='{slot.game}'")

        item_amounts: dict[int, int] = {}
        for item_id in item_ids:
            if item_id not in item_amounts:
                item_amounts.update({item_id: 0})
            item_amounts[item_id] += 1

        for item_id, item_amount in item_amounts.items():
            inventory.append(InventoryCsv(
                player=slot.name,
                game=slot.game,
                item_name=[k for k, v in datapackage.items() if v == item_id][0],
                item_amount=item_amount
            ))

    table_headers: list[str] = ["Player", "Game", "Item", "Amount"]
    if output_inventory_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}_start_inventory.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(inventory)
            print(f"\nWrote detailed start inventory table to {output_file}")

    if output_inventory_table:
        print("\nDetailed start inventory table")
        print(tabulate(tabular_data=inventory, headers=table_headers, tablefmt="rounded_outline"))

# TODO - Show last sphere per player
