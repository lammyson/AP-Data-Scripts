import argparse
import orjson
from pathlib import Path
from typing import Any
import yaml


def positive_int(val) -> int:
    i: int = int(val)
    if i < 1:
        raise argparse.ArgumentTypeError(f"invalid value: '{val}'. Value must be >= 1")
    return i


parser = argparse.ArgumentParser(
    description="Does something like `- priority_locations: random` with weighted options for each location")
parser.add_argument(
    "-d", "--datapackage-export",
    required=True,
    type=Path,
    metavar="datapackage_export.json",
    help="(Required) datapackage_export.json file. Created by running ArchipelagoLauncher -> Export Datapackage")
parser.add_argument(
    "-y", "--player-yaml",
    required=True,
    type=Path,
    help="(Required) Player yaml file to update")

parser.add_argument(
    "-t", "--true-weight",
    type=positive_int,
    default=1,
    metavar="WEIGHT",
    help="Weight for the true option. Default is 1")
parser.add_argument(
    "-f", "--false-weight",
    type=positive_int,
    default=1,
    metavar="WEIGHT",
    help="Weight for the false option. Default is 1")
parser.add_argument(
    "-c", "--concise",
    default=False,
    action="store_true",
    help="Print the triggers in a more concise way")
args = parser.parse_args()

true_weight: int = args.true_weight
false_weight: int = args.false_weight
concise: bool = args.concise

datapackage_file: Path = args.datapackage_export
player_yaml_file: Path = args.player_yaml
output_yaml_file: Path = Path(f"{player_yaml_file.parent}/{player_yaml_file.stem}_with_priority_locations.yaml")

with open(datapackage_file, "rb") as f:
    datapackage: dict[str, Any] = orjson.loads(f.read())
with open(player_yaml_file, "rb") as f:
    player_yaml = yaml.safe_load(f)

game: str = player_yaml["game"]

print(f"Using {{true: {true_weight}, false: {false_weight}}} for weights")
print(f"Total possible locations: {len(datapackage["games"][game]["location_name_to_id"])}")

adverb = "verbosely"
if concise:
    adverb = "concisely"
print(f"Writing new yaml to {output_yaml_file} {adverb}")
Path.copy(player_yaml_file, output_yaml_file)

if concise:
    with open(output_yaml_file, "a") as f:
        f.write("\n")

        for location in datapackage["games"][game]["location_name_to_id"].keys():
            f.write(f"  \"add_{location}\": {{true: {true_weight}, false: {false_weight}}}\n")
        f.write("\n")

        f.write("  triggers:\n")
        for location in datapackage["games"][game]["location_name_to_id"].keys():
            orjson.dumps
            f.write(f"    - {{option_category: \"{game}\", option_name: \"add_{location}\", option_result: true, options: {{\"{game}\": {{+priority_locations: [\"{location}\"]}}}}}}\n")
else:
    with open(output_yaml_file, "a") as f:
        f.write("\n")

        for location in datapackage["games"][game]["location_name_to_id"].keys():
            f.write(f"  \"add_{location}\":\n")
            f.write(f"    true: {true_weight}\n")
            f.write(f"    false: {false_weight}\n")
        f.write("\n")

        f.write("  triggers:\n")
        for location in datapackage["games"][game]["location_name_to_id"].keys():
            f.write(f"    - option_category: \"{game}\"\n")
            f.write(f"      option_name: \"add_{location}\"\n")
            f.write("      option_result: true\n")
            f.write("      options:\n")
            f.write(f"        \"{game}\":\n")
            f.write("          +priority_locations:\n")
            f.write(f"            - \"{location}\"\n")
