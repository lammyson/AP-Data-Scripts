import argparse
import csv
import json
from pathlib import Path
import sys
from tabulate import tabulate, SEPARATING_LINE
from typing import Any, NamedTuple
import warnings
import zlib


# TODO - Add item_link support


def convert_sets_to_lists(obj: dict | list | set) -> dict[Any, Any] | list[Any]:
    """Recursively converts sets to lists inside a dict or list"""
    if isinstance(obj, dict):
        return {key: convert_sets_to_lists(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(item) for item in obj]
    elif isinstance(obj, set):
        return [convert_sets_to_lists(item) for item in obj]
    return obj


def item_flags_to_string(item_flags: int) -> str:
    item_classifications: list[str] = []
    if item_flags & 0b001:
        item_classifications.append("Progression")
    if item_flags & 0b010:
        item_classifications.append("Useful")
    if item_flags & 0b100:
        item_classifications.append("Trap")
    if item_flags == 0:
        item_classifications.append("Filler")
    return ", ".join(item_classifications)


class SummaryTableRow(NamedTuple):
    id: int
    name: str
    game: str
    locations: int
    num_priority_locations: int
    num_priority_locations_percent: str
    num_hints_finder: int
    num_hints_receiver: int
    num_start_inventory: int


class HintCsv(NamedTuple):
    """For printing hints to a CSV file to make a table similar to the Archipelago tracker page"""
    finding_player: str
    receiving_player: str
    item_name: str
    item_classification: str
    location_name: str
    finding_game: str
    receiving_game: str
    entrance: str


class InventoryCsv(NamedTuple):
    """For printing start inventory to a CSV file"""
    id: int
    player: str
    game: str
    item_name: str
    item_amount: int


# TODO - Should finding/receiving games be added?
# ["Sphere Id", "Finding Player", "Receiving Player", "Location", "Item", "Classification"]
class DetailedSphereCsv(NamedTuple):
    """For printing sphere info to a CSV file"""
    id: int
    finding_player: str
    receiving_player: str
    finding_game: str
    location_name: str
    item_name: str
    item_classification: str


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
    "--output-csv-all",
    default=False,
    action="store_true",
    help="Output csv files of all data")
parser.add_argument(
    "--output-table-all",
    default=False,
    action="store_true",
    help="Output all tables to terminal. "
         "NOTE: This can be giant. Recommend --output-csv-all option or choosing specific --output-*-table option(s)")

parser.add_argument(
    "-d", "--debug",
    default=False,
    action="store_true",
    help=argparse.SUPPRESS)
parser.add_argument(
    "--output-locations",
    default=False,
    action="store_true",
    help=argparse.SUPPRESS)
parser.add_argument(
    "--output-server-options",
    default=False,
    action="store_true",
    help=argparse.SUPPRESS)

detailed_summary_group = parser.add_argument_group("Detailed summary options")
detailed_summary_group.add_argument(
    "--output-summary-csv",
    default=False,
    action="store_true",
    help="Output a csv file of the detailed summary")
detailed_summary_group.add_argument(
    "--output-summary-table",
    default=False,
    action="store_true",
    help="Print the detailed summary to the terminal as a table. "
         "NOTE: This can be giant. Recommend --output-summary-csv option when there's a large number of players")

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

detailed_spheres_group = parser.add_argument_group("Detailed spheres options")
detailed_spheres_group.add_argument(
    "--output-spheres-summary-csv",
    default=False,
    action="store_true",
    help="Output a csv file of summary spheres info")
detailed_spheres_group.add_argument(
    "--output-spheres-detailed-csv",
    default=False,
    action="store_true",
    help="Output a csv file of detailed spheres info")
detailed_spheres_group.add_argument(
    "--output-spheres-summary-table",
    default=False,
    action="store_true",
    help="Print the summary spheres info to the terminal as a table. "
         "NOTE: This can be giant. Recommend --output-spheres-summary-csv option")
detailed_spheres_group.add_argument(
    "--output-spheres-detailed-table",
    default=False,
    action="store_true",
    help="Print the spheres info to the terminal as a table. "
         "NOTE: This can be giant. Recommend --output-spheres-detailed-csv option")

args = parser.parse_args()

debug: bool = args.debug
output_locations: bool = args.output_locations
output_server_options: bool = args.output_server_options

output_summary_csv: bool = args.output_summary_csv
output_summary_table: bool = args.output_summary_table

output_hints_csv: bool = args.output_hints_csv
output_hints_table: bool = args.output_hints_table

output_inventory_csv: bool = args.output_inventory_csv
output_inventory_table: bool = args.output_inventory_table

output_spheres_summary_csv: bool = args.output_spheres_summary_csv
output_spheres_detailed_csv: bool = args.output_spheres_detailed_csv
output_spheres_summary_table: bool = args.output_spheres_summary_table
output_spheres_detailed_table: bool = args.output_spheres_detailed_table

# Override csv output if enabled
output_csv_all: bool = args.output_csv_all
if output_csv_all:
    output_summary_csv = True
    output_hints_csv = True
    output_inventory_csv = True
    output_spheres_summary_csv = True
    output_spheres_detailed_csv = True

# Override table output if enabled
output_table_all: bool = args.output_table_all
if output_table_all:
    output_summary_table = True
    output_hints_table = True
    output_inventory_table = True
    output_spheres_summary_table = True
    output_spheres_detailed_table = True

output_summary: bool = output_summary_csv or output_summary_table
output_detailed_hints: bool = output_hints_csv or output_hints_table
output_detailed_inventory: bool = output_inventory_csv or output_inventory_table
output_spheres: bool = output_spheres_summary_csv or output_spheres_detailed_csv or \
                       output_spheres_summary_table or output_spheres_detailed_table

# TODO - add some basic file validation
file: Path = args.input_file
with open(file, 'rb') as f:
    raw_data = f.read()
print(f"Using file={file}")
print()

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
            json.dump(convert_sets_to_lists(multidata), f, indent=2) # pyright: ignore[reportArgumentType]
        print(f"Saved human readable version of server file to {output_file}")
        print()

num_players: int = len(multidata["slot_info"])

num_locations_per_player: list[int] = [0] * (num_players+1)
num_priority_locations_per_player: list[int] = [0] * (num_players+1)
num_locations: int = 0
for player_id, locations in multidata["locations"].items():
    player_locations: int = len(locations)
    num_locations += player_locations
    num_locations_per_player[player_id] = player_locations
    num_priority_locations_per_player[player_id] = len([item_id for item_id, receiving_player_id, item_flags in locations.values() if item_flags & 0b1])

num_start_inventory_per_player: list[int] = [0] * (num_players+1)
num_start_inventory: int = 0
for player_id, items in multidata["precollected_items"].items():
    player_start_inventory = len(items)
    num_start_inventory += player_start_inventory
    num_start_inventory_per_player[player_id] = player_start_inventory

# Process hints
num_start_hints_finder: list[int] = [0] * (num_players+1)
num_start_hints_receiver: list[int] = [0] * (num_players+1)
hints: set[Hint] = set()
for player_hints in multidata["precollected_hints"].values():
    for hint in player_hints:
        if hint not in hints:
            hints.add(hint)
            num_start_hints_finder[hint.finding_player] += 1
            num_start_hints_receiver[hint.receiving_player] += 1

# Print a quick summary
print(f"Quick summary:")
print(f"\tGenerated on version {".".join([str(v) for v in multidata["version"]])}")
print(f"\tNumber of players={num_players}")
print(f"\tNumber of locations={num_locations}")
print(f"\tNumber of spheres={len(multidata["spheres"])}")
print(f"\tNumber of start_inventory={num_start_inventory}")
print(f"\tNumber of start_hints={len(hints)}")
print()

# Print a detailed summary
if output_summary:
    table_headers = ["Id", "Name", "Game", "Locations", "Priority Locations", "Priority %", "Start Hints - Finder", "Start Hints - Receiver", "Start Inventory"]
    table_data: list = []
    for slot_id, player in multidata["slot_info"].items():
        table_data.append(SummaryTableRow(
            id=slot_id,
            name=player.name,
            game=player.game,
            locations=num_locations_per_player[slot_id],
            num_priority_locations=num_priority_locations_per_player[slot_id],
            num_priority_locations_percent=f"{num_priority_locations_per_player[slot_id] / num_locations_per_player[slot_id] * 100:>7.3f} %",
            num_hints_finder=num_start_hints_finder[slot_id],
            num_hints_receiver=num_start_hints_receiver[slot_id],
            num_start_inventory=num_start_inventory_per_player[slot_id]
        ))

    if output_summary_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}_summary.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(table_data)
        print(f"Wrote summary table to {output_file}")

    if output_summary_table:
        table_data.append(SEPARATING_LINE)
        table_data.append(["", "", "Totals", num_locations, sum(num_priority_locations_per_player), "", sum(num_start_hints_finder), sum(num_start_hints_receiver), num_start_inventory])
        print("\nSummary Table")
        print(tabulate(tabular_data=table_data, headers=table_headers, tablefmt="rounded_outline", preserve_whitespace=True))
        print()

# Print detailed hints
if output_detailed_hints:
    hints_processed: list[HintCsv] = []
    for hint in hints:
        finding_slot = multidata["slot_info"][hint.finding_player]
        receiving_slot = multidata["slot_info"][hint.receiving_player]
        finding_datapackage = multidata["datapackage"][finding_slot.game]["location_name_to_id"] # pyright: ignore[reportTypedDictNotRequiredAccess]
        receiving_datapackage = multidata["datapackage"][receiving_slot.game]["item_name_to_id"] # pyright: ignore[reportTypedDictNotRequiredAccess]

        location = [k for k, v in finding_datapackage.items() if v == hint.location]
        item = [k for k, v in receiving_datapackage.items() if v == hint.item]
        hints_processed.append(HintCsv(
            finding_player=finding_slot.name,
            receiving_player=receiving_slot.name,
            item_name=item[0],
            item_classification=item_flags_to_string(hint.item_flags),
            location_name=location[0],
            finding_game=finding_slot.game,
            receiving_game=receiving_slot.game,
            entrance=hint.entrance
        ))

    table_headers: list[str] = ["Finder", "Receiver", "Item", "Classification", "Location", "Finding Game", "Receiving Game", "Entrance"]
    if output_hints_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}_start_hints.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(hints_processed)
        print(f"Wrote detailed start hints table to {output_file}")

    if output_hints_table:
        print("\nDetailed start hints table")
        print(tabulate(tabular_data=hints_processed, headers=table_headers, tablefmt="rounded_outline"))
        print()

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
                id=player_id,
                player=slot.name,
                game=slot.game,
                item_name=[k for k, v in datapackage.items() if v == item_id][0],
                item_amount=item_amount
            ))

    table_headers: list[str] = ["Id", "Player", "Game", "Item", "Amount"]
    if output_inventory_csv:
        output_file: Path = Path(f"{file.parent}/{file.stem}_start_inventory.csv")
        with open(output_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(table_headers)
            writer.writerows(inventory)
        print(f"Wrote detailed start inventory table to {output_file}")

    if output_inventory_table:
        print("\nDetailed start inventory table")
        print(tabulate(tabular_data=inventory, headers=table_headers, tablefmt="rounded_outline"))
        print()

# TODO - Print locations per player
# locations are dicts of player to dict of locations to (item_id, receiving_player_id, item_flags)
# for location_id, (item_id, receiving_player, item_flags) in check_data.items():
if output_locations:
    print("output_locations not implemented yet")
    print()

# TODO - Show first and last sphere per player (except sphere 1)

# Print spheres
if output_spheres:
    # Spheres summary
    if output_spheres_summary_csv or output_spheres_summary_table:
        sphere_table: list = []
        rolling_location_count: int = 0
        for sphere_id, sphere in enumerate(multidata["spheres"]):
            player_ids: list[int] = []
            player_names: list[str] = []
            num_sphere_locations: int = 0
            for player_id, location_ids in sphere.items():
                player_ids.append(player_id)
                player_names.append(multidata["slot_info"][player_id].name)
                num_sphere_locations += len(location_ids)
            rolling_location_count += num_sphere_locations
            sphere_table.append([sphere_id+1, len(player_ids), num_sphere_locations, rolling_location_count, f"{rolling_location_count / num_locations * 100:>7.3f} %"])

        table_headers: list[str] = ["Sphere Id", "Num Players", "Num Locations", "Total Locations", "Location %"]
        if output_spheres_summary_csv:
            output_file: Path = Path(f"{file.parent}/{file.stem}_spheres_summary.csv")
            with open(output_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerow(table_headers)
                writer.writerows(sphere_table)
            print(f"Wrote spheres summary table to {output_file}")

        if output_spheres_summary_table:
            print("\nSpheres summary")
            print(tabulate(tabular_data=sphere_table, headers=table_headers, tablefmt="rounded_outline", preserve_whitespace=True))
            print()

    # Detailed spheres
    if output_spheres_detailed_csv or output_spheres_detailed_table:
        sphere_table: list = []
        for sphere_id, sphere in enumerate(multidata["spheres"]):
            for player_id, location_ids in sphere.items():
                finding_slot = multidata["slot_info"][player_id]
                finding_datapackage = multidata["datapackage"][finding_slot.game]["location_name_to_id"] # pyright: ignore[reportTypedDictNotRequiredAccess]

                for location_id in location_ids:
                    item_id, receiving_player_id, item_flags = multidata["locations"][player_id][location_id]
                    receiving_slot = multidata["slot_info"][receiving_player_id]
                    receiving_datapackage = multidata["datapackage"][receiving_slot.game]["item_name_to_id"] # pyright: ignore[reportTypedDictNotRequiredAccess]

                    location = [k for k, v in finding_datapackage.items() if v == location_id]
                    item = [k for k, v in receiving_datapackage.items() if v == item_id]

                    sphere_table.append(DetailedSphereCsv(
                        id=sphere_id+1,
                        finding_player=finding_slot.name,
                        receiving_player=receiving_slot.name,
                        finding_game=finding_slot.game,
                        location_name=location[0],
                        item_name=item[0],
                        item_classification=item_flags_to_string(item_flags)
                    ))

        table_headers: list[str] = ["Sphere Id", "Finding Player", "Receiving Player", "Game", "Location", "Item", "Classification"]
        if output_spheres_detailed_csv:
            output_file: Path = Path(f"{file.parent}/{file.stem}_spheres_detailed.csv")
            with open(output_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerow(table_headers)
                writer.writerows(sphere_table)
            print(f"Wrote detailed spheres table to {output_file}")

        if output_spheres_detailed_table:
            print("\nDetailed spheres table")
            print(tabulate(tabular_data=sphere_table, headers=table_headers, tablefmt="rounded_outline"))
            print()

# Print server_options
if output_server_options:
    print("Server options:")
    for key, value in multidata["server_options"].items():
        print(f"\t{key}: {value}")
