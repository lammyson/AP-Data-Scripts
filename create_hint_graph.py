import argparse
from dataclasses import asdict, dataclass
import enum
import pygraphviz
import json
from pathlib import Path
from typing import Any, NamedTuple
import time

from get_room_data import get_file_safe_name

# TODO - Split this into 2 scripts
# - One that processes the raw hints into hints_processed.json
# - One that reads hints_processed.json and does all the display stuff


# https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/network%20protocol.md#hintstatus
class HintStatus(enum.IntEnum):
    HINT_UNSPECIFIED = 0   # The receiving player has not specified any status
    HINT_NO_PRIORITY = 10  # The receiving player has specified that the item is unneeded
    HINT_AVOID = 20        # The receiving player has specified that the item is detrimental
    HINT_PRIORITY = 30     # The receiving player has specified that the item is needed
    HINT_FOUND = 40        # The location has been collected. Status cannot be changed once found.


# https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/network%20protocol.md#hint
class Hint(NamedTuple):
    receiving_player: int
    finding_player: int
    location: int
    item: int
    found: bool
    entrance: str = ""
    item_flags: int = 0
    status: HintStatus = HintStatus.HINT_UNSPECIFIED


# Internal hint type to make creating the hint graph easier
class HintProcessed(NamedTuple):
    finding_player: int
    receiving_player: int
    location_id: int
    location_name: str  # Save the location_id lookup
    item_id: int
    item_name: str  # Save the item_id lookup
    entrance: str


# Internal hint type to make creating the hint graph easier
@dataclass
class PlayerHints:
    player_num: int
    slot_name: str
    game: str
    alias: str | None
    has_goaled: bool
    has_hint: bool
    is_item_link: bool
    node_name: str
    hints_to_find: list[HintProcessed]
    hints_for_others: list[HintProcessed]


def set_node_name(slot_name: str, alias: str | None, is_item_link: bool) -> str:
    if alias:
        node_name = f"{alias} ({slot_name})"
    elif is_item_link:
        node_name = f"item_link: {slot_name}"
    else:
        node_name = f"{slot_name}"
    return node_name


def main():
    parser = argparse.ArgumentParser(
        description="Create a hint graph of a room's hints. "
        "Graphs all hints by default. "
        "Requires room data from get_room_data.py")
    parser.add_argument(
        "-f", "--data-folder",
        required=True,
        type=Path,
        metavar="FOLDER",
        help="(Required) Folder containing room data retrieved by get_room_data.py")

    parser.add_argument(
        "-d", "--debug",
        default=False,
        action="store_true",
        help="Print debug statements and files")
    parser.add_argument(
        "-hs", "--highlight-slots",
        nargs="*",
        metavar="SLOT",
        help="List of slot names to highlight in the hint graph")
    parser.add_argument(
        "--show-entrances",
        default=False,
        action="store_true",
        help="Show entrance info in the hint graph. Warning: This can add a lot of bloat to the hint graph")
    parser.add_argument(
        "--show-goaled-slots",
        default=False,
        action="store_true",
        help="Show goaled slots that have not received their hinted progression items")

    hint_chain_group = parser.add_argument_group("Hint chain options (optional)")
    hint_chain_group.add_argument(
        "--hint-chain-slot",
        metavar="SLOT",
        help="Slot name of the slot the hint chain will be centered around. "
        "Requires one of the --[child-|parent-]depth options")
    hint_chain_group.add_argument(
        "--depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint chain to display in both directions. "
        "Requires the --hint-chain-slot option")
    hint_chain_group.add_argument(
        "--child-depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint chain to display for slots that depend on you. "
        "Requires the --hint-chain-slot option. Overrides --depth option")
    hint_chain_group.add_argument(
        "--parent-depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint chain to display for slots that you depend on. "
        "Requires the --hint-chain-slot option. Overrides --depth option")

    output_group = parser.add_argument_group("File output options (optional)")
    output_group.add_argument(
        "-o", "--output-filename",
        metavar="FILE",
        help="Partial output filename for the graph. "
        "Data fetch date and extension are appended. "
        "Example: <output-filename>_<fetch-date>.svg")
    output_group.add_argument(
        "--output-format",
        default="svg",
        choices=["svg", "jpg"],
        help="Output file format. Default is svg")
    output_group.add_argument(
        "--output-engine",
        default="dot",
        choices=["dot", "circo"],
        help="Layout engine for graphviz to use when creating the hint graph. "
        "Default is dot")

    args = parser.parse_args()
    debug: bool = args.debug

    if debug:
        print("Just after argument parsing")
        print(f"\tdata-folder={args.data_folder}")
        print(f"\thighlight-slots={args.highlight_slots}")
        print(f"\tshow-entrances={args.show_entrances}")
        print(f"\tshow-goaled-slots={args.show_goaled_slots}")
        print(f"\thint-chain-slot={args.hint_chain_slot}")
        print(f"\tdepth={args.depth}")
        print(f"\tchild-depth={args.child_depth}")
        print(f"\tparent-depth={args.parent_depth}")
        print(f"\toutput-filename={args.output_filename}")
        print(f"\toutput-format={args.output_format}")
        print(f"\toutput-engine={args.output_engine}")
        print("")

    show_entrances: bool = args.show_entrances
    show_goaled_slots: bool = args.show_goaled_slots
    output_format = args.output_format
    output_engine = args.output_engine

    if not args.data_folder.exists():
        parser.error(f"Data folder={args.data_folder} does not exist")
    if not Path(args.data_folder).is_dir():
        parser.error(f"Data folder={args.data_folder} is not a directory")

    show_parent_nodes: bool = False
    show_child_nodes: bool = False
    parent_depth: int = 2147483647
    child_depth: int = 2147483647

    if args.depth:
        show_parent_nodes = True
        parent_depth = args.depth
        show_child_nodes = True
        child_depth = args.depth
    if args.parent_depth:
        show_parent_nodes = True
        parent_depth = args.parent_depth
    if args.child_depth:
        show_child_nodes = True
        child_depth = args.child_depth

    depth_option_provided: bool = args.depth is not None or args.parent_depth is not None or args.child_depth is not None
    hint_chain_slot_provided: bool = args.hint_chain_slot is not None
    if depth_option_provided and not hint_chain_slot_provided:
        parser.error("The --hint-chain-slot argument is required when using --depth|--child-depth|--parent-depth")
    if hint_chain_slot_provided and not depth_option_provided:
        parser.error("At least one of the --depth|--child-depth|--parent-depth arguments are required "
                     "when using --hint-chain-slot")

    # TODO - Filter out nodes with >= some number of hints to find - Make this configurable
    high_hint_count: int = 2147483647

    # Load required data from cached API data
    data_folder: str = args.data_folder
    with open(f"{data_folder}/last_fetched.json", "r") as f:
        last_fetched = json.load(f)
    with open(f"{data_folder}/players.json", "r") as f:
        players: list[dict[str, str]] = json.load(f)
    with open(f"{data_folder}/tracker.json", "r") as f:
        tracker = json.load(f)
    with open(f"{data_folder}/static_tracker.json", "r") as f:
        static_tracker = json.load(f)
    room_datapackages: dict[str, dict[str, Any]] = dict()
    for game, data in static_tracker["datapackage"].items():
        safe_game_name: str = get_file_safe_name(game)
        checksum: str = data["checksum"]
        datapackage_file = f".datapackages/{safe_game_name}/{checksum}.json"
        if Path(datapackage_file).is_file():
            with open(datapackage_file) as f:
                room_datapackages.update({game: json.load(f)})
        else:
            print(f"{datapackage_file} is required but does not exist. Run get_room_data.py first")
            exit(1)

    # Validate slot id if it was provided
    hint_chain_slot_id: int = -1

    # Validate slot name if it was provided
    # TODO - support item_links
    hint_chain_slot_name: str | None = args.hint_chain_slot
    if hint_chain_slot_name:
        matches = [[idx, player] for idx, player in enumerate(players) if player["name"] == hint_chain_slot_name]

        if len(matches) == 0:
            parser.error(f"Error parsing --hint-chain-slot. "
                         f"slot_name={hint_chain_slot_name} not found. "
                         "Please check your spelling")
        elif len(matches) >= 2:
            error_json = []
            for match in matches:
                error_json.append({
                    "alias": tracker["aliases"][match[0]+1]["alias"],
                    "player": match[0]+1,
                    "slot_name": match[1][0]
                })
            parser.error(f"Error parsing --hint-chain-slot. "
                         f"slot_name={hint_chain_slot_name} found multiple times. "
                         "This should never happen. "
                         f"Run get-room-info.py to pull fresh data\n\t{error_json}")

        hint_chain_slot_id = matches[0][0]+1

    # Validate slot names to highlight exist
    slot_ids_to_highlight: list[int] = []
    highlight_slots: list[str] = args.highlight_slots
    if highlight_slots:
        for slot in highlight_slots:
            matches = [[idx, player] for idx, player in enumerate(players) if player["name"] == slot]

            if len(matches) == 0:
                parser.error(f"Error parsing --highlight-slots. "
                             f"slot_name={slot} not found. "
                             "Please check your spelling")
            elif len(matches) >= 2:
                error_json = []
                for match in matches:
                    error_json.append({
                        "alias": tracker["aliases"][match[0]+1]["alias"],
                        "player": match[0]+1,
                        "slot_name": match[1][0]
                    })
                parser.error(f"Error parsing --highlight-slots. "
                             f"slot_name={slot} found multiple times. "
                             "This should never happen. "
                             f"Run get-room-info.py to pull fresh data\n\t{error_json}")

            slot_ids_to_highlight.append(matches[0][0]+1)

    # Create output filename
    fetch_time: str = last_fetched["last_fetched"]
    output_filename: Path = Path(f"{fetch_time}")
    if args.output_filename is not None:
        output_filename = Path(f"{output_filename}_{args.output_filename}")

    if debug:
        print("Just after argument validation")
        print(f"\tdata-folder={data_folder}")
        print(f"\thighlight-slots={highlight_slots}")
        print(f"\tshow-entrances={show_entrances}")
        print(f"\tshow-goaled-slots={show_goaled_slots}")
        print(f"\thint-chain-slot={hint_chain_slot_name}")
        print(f"\tshow_parent_nodes={show_parent_nodes}")
        print(f"\tparent_depth={parent_depth}")
        print(f"\tshow_child_nodes={show_child_nodes}")
        print(f"\tchild_depth={child_depth}")
        print(f"\toutput_filename={output_filename}")
        print(f"\toutput_format={output_format}")
        print(f"\toutput_engine={output_engine}")
        print("")

        Path(f"{data_folder}/make-hint-graph-debug").mkdir(parents=True, exist_ok=True)

    # Validation done. Tell the user what type of hint graph will be created
    action_string: str = "Creating hint"
    if depth_option_provided:
        action_string += f" chain for slot {players[hint_chain_slot_id-1]["name"]} showing"
        if show_parent_nodes and show_child_nodes:
            action_string += f" parent nodes at depth {parent_depth} and child nodes at depth {child_depth}"
        elif show_parent_nodes:
            action_string += f" parent nodes at depth {parent_depth}"
        elif show_child_nodes:
            action_string += f" child nodes at depth {child_depth}"
    else:
        action_string += " graph for the entire multiworld"
    action_string += f" using layout engine {output_engine} and file format {output_format}"

    if highlight_slots:
        action_string += f"\n- And highlighting the following slots: {highlight_slots}"

    if show_entrances:
        action_string += "\n- And showing entrance information"

    if show_goaled_slots:
        action_string += "\n- And showing goaled slots that have not received their hinted progression items"

    print(action_string)

    # Flatten all the tracker["hints"][idx]["hints"] into a single list of dicts while getting rid of dupes
    # Add 1 for the special Archipelago slot at slot 0
    finding_player_count = [0] * (len(static_tracker["player_game"]) + len(static_tracker["groups"]) + 1)
    hints_raw_unique: list[Hint] = []
    for hint_dict in tracker["hints"]:
        for h in hint_dict["hints"]:
            hint = Hint._make(h)
            if hint not in hints_raw_unique:
                hints_raw_unique.append(hint)

                # Count how many unfound progression hints a slot has been hinted to find
                if not hint.found and (hint.item_flags & 0x1 == 1):
                    finding_player_count[hint.finding_player] += 1
    high_hint_count_slots = [index + 1 for index, value in enumerate(finding_player_count) if value >= high_hint_count]

    if debug:
        with open(f"{data_folder}/make-hint-graph-debug/hints_raw_unique.json", "w") as f:
            json.dump(hints_raw_unique, f, indent=3)

    # Create the initial list of hints with
    hints_processed: list[PlayerHints] = []

    # Add the special Archipelago slot (also makes indexing 0-based yay!)
    hints_processed.append(PlayerHints(
        player_num=0,
        slot_name="Archipelago",
        game="Archipelago",
        alias=None,
        has_goaled=True,
        hints_to_find=[],
        hints_for_others=[],
        has_hint=False,
        is_item_link=False,
        node_name="Archipelago"
    ))

    # Add the normal slots
    for (idx, player) in enumerate(players):
        hints_processed.append(PlayerHints(
            player_num=tracker["aliases"][idx]["player"],
            slot_name=player["name"],
            game=player["game"],
            alias=tracker["aliases"][idx]["alias"],
            has_goaled=tracker["player_status"][idx]["status"] == 30,
            hints_to_find=[],
            hints_for_others=[],
            has_hint=False,
            is_item_link=False,
            node_name=set_node_name(slot_name=player["name"], alias=tracker["aliases"][idx]["alias"], is_item_link=False)
        ))

    # Add item_links slots
    for item_link in static_tracker["groups"]:
        hints_processed.append(PlayerHints(
            player_num=item_link["slot"],
            slot_name=item_link["name"],
            game=hints_processed[item_link["members"][0]-1].game,
            alias=None,
            has_goaled=False,
            hints_to_find=[],
            hints_for_others=[],
            has_hint=False,
            is_item_link=True,
            node_name=set_node_name(slot_name=item_link["name"], alias=None, is_item_link=True)
        ))

    if debug:
        with open(f"{data_folder}/make-hint-graph-debug/hints_processed_pre.json", "w") as f:
            json.dump([asdict(hint) for hint in hints_processed], f, indent=3)

    # Add hints to hints_processed
    for hint in hints_raw_unique:
        # Skip hints that were found
        if hint.found:
            continue

        # Skip non-progression hints
        if hint.item_flags & 0x1 != 1:
            continue

        # Skip received hints from slots that are goaled
        if not show_goaled_slots and hints_processed[hint.receiving_player].has_goaled:
            continue

        # Skip slots that have way too many unfound progression hints to find
        if hint.finding_player in high_hint_count_slots:
            continue

        location = [k for k, v in room_datapackages[hints_processed[hint.finding_player].game]["location_name_to_id"].items()
                    if v == hint.location]
        item = [k for k, v in room_datapackages[hints_processed[hint.receiving_player].game]["item_name_to_id"].items()
                if v == hint.item]

        hints_processed[hint.finding_player].hints_to_find.append(HintProcessed(
            finding_player=hint.finding_player,
            receiving_player=hint.receiving_player,
            location_id=hint.location,
            location_name=location[0],
            item_id=hint.item,
            item_name=item[0],
            entrance=hint.entrance
        ))
        hints_processed[hint.receiving_player].hints_for_others.append(HintProcessed(
            finding_player=hint.finding_player,
            receiving_player=hint.receiving_player,
            location_id=hint.location,
            location_name=location[0],
            item_id=hint.item,
            item_name=item[0],
            entrance=hint.entrance
        ))
        hints_processed[hint.receiving_player].has_hint = True
        hints_processed[hint.finding_player].has_hint = True
    if debug:
        with open(f"{data_folder}/make-hint-graph-debug/hints_processed.json", "w") as f:
            json.dump([asdict(hint) for hint in hints_processed], f, indent=3)

    # Create list of nodes to show
    visited_nodes: set[int] = set()

    # Show all nodes if we're not looking for a specific chain
    if not show_child_nodes and not show_parent_nodes:
        visited_nodes.update([node.player_num for node in hints_processed])

    # Show nodes that depend on us
    if show_child_nodes:
        nodes: list[PlayerHints] = [hints_processed[hint_chain_slot_id]]
        visited_nodes_child: set = set([hints_processed[hint_chain_slot_id].player_num])
        while nodes and child_depth > 0:
            child_depth -= 1
            current_node = nodes.pop()
            for hint in current_node.hints_to_find:
                if hint.receiving_player not in visited_nodes_child:
                    visited_nodes_child.add(hint.receiving_player)
                    nodes.append(hints_processed[hint.receiving_player])
        visited_nodes.update(visited_nodes_child)

    # Show nodes that we depend on
    if show_parent_nodes:
        nodes: list[PlayerHints] = [hints_processed[hint_chain_slot_id]]
        visited_nodes_parent: set = set([hints_processed[hint_chain_slot_id].player_num])
        while nodes and parent_depth > 0:
            parent_depth -= 1
            current_node = nodes.pop()
            for hint in current_node.hints_for_others:
                if hint.finding_player not in visited_nodes_parent:
                    visited_nodes_parent.add(hint.finding_player)
                    nodes.append(hints_processed[hint.finding_player])
        visited_nodes.update(visited_nodes_parent)

    # Create the graph
    dot = pygraphviz.AGraph(directed=True, rankdir='LR')

    # Highlight nodes if they are called out even if they won't connect to the graph with current settings
    if slot_ids_to_highlight:
        for slot_id in slot_ids_to_highlight:
            dot.add_node(f"{hints_processed[slot_id].player_num}",
                         label=hints_processed[slot_id].node_name,
                         color="darkgreen",
                         fillcolor="darkgreen",
                         style="filled",
                         fontcolor="white")

    # Add all hints
    for index in visited_nodes:
        player = hints_processed[index]
        if player.has_hint:
            dot.add_node(f"{player.player_num}", label=player.node_name)
            for hint in player.hints_to_find:
                if hint.finding_player in visited_nodes and hint.receiving_player in visited_nodes:
                    label = f"{hint.item_name} at {hint.location_name}"
                    if hint.entrance and show_entrances:
                        label = f"{label} ({hint.entrance})"
                    dot.add_edge(u=f"{hint.finding_player}",
                                 v=f"{hint.receiving_player}",
                                 label=label)

    # Save it!
    print(f"Saving to {data_folder}/graphs/{output_filename}.{output_format}")
    Path(f"{data_folder}/graphs").mkdir(parents=True, exist_ok=True)

    start_time = time.perf_counter()
    dot.draw(path=f"{data_folder}/graphs/{output_filename}.{output_format}", format=output_format, prog=output_engine)
    end_time = time.perf_counter()

    execution_time = end_time - start_time
    print(f"Hint graph creation took {execution_time:.6f} seconds to run")


if __name__ == "__main__":
    main()
