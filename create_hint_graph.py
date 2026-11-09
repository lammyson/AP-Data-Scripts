import argparse
from dataclasses import asdict, dataclass
import enum
import io
import pygraphviz
import json
from pathlib import Path
from PIL import Image
from typing import Any, NamedTuple
import time
import yaml

from get_room_data import get_file_safe_name, RoomData, SlotMapping

# TODO - Make this into a library
# - Function that processes the raw hints into hints_processed.json
# - Function that takes the data from hints_processed.json and does all the display stuff
# So then we can make a python script that does
# - Process hints into hints_processed.json once
# - Call the hint graph creation function multiple times with different args depending on what we want

class HintMode(enum.IntEnum):
    HINT_GRAPH_MODE = 0     # Show the full hint graph
    HINT_SUBGRAPH_MODE = 1  # Show a subgraph from the full hint graph
    HINT_CHAIN_MODE = 2     # Show a smaller set of a subgraph with only certain directions displayed


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


class HintProcessed(NamedTuple):
    """Internal hint type to make creating the hint graph easier"""
    finding_player: int
    receiving_player: int
    location_name: str
    item_name: str
    found: bool
    entrance: str
    item_flags: int
    status: HintStatus


@dataclass
class PlayerHints:
    """Internal hint type to make creating the hint graph easier"""
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


# TODO - I really need to define what finder and receiver means (or find alternative labels and definitions) because I can never remember which
# node is the reference frame
# upstream/downstream?
class HintChainDirection(enum.StrEnum):
    FINDER = "finder"
    RECEIVER = "receiver"


class HintChainConfig(NamedTuple):
    name: str
    hint_chain: list[str]
    direction: HintChainDirection
    search_last_slot: bool


def get_slot_ids_from_names(slot_names: list[str], slot_mapping: list[SlotMapping]) -> list[int]:
    """Get list of 1-based slot ids from a list of slot names"""
    if slot_names is None or slot_mapping is None:
        return []

    slot_ids: list[int] = []
    for slot_name in slot_names:
        matches = [player for player in slot_mapping if player.name == slot_name]

        if len(matches) == 0:
            raise KeyError(f"slot_name={slot_name} not found in slot_mapping.json. "
                            "Please check your spelling")
        elif len(matches) >= 2:
            raise KeyError(f"slot_name={slot_name} found multiple times. This should never happen. "
                            "Run get-room-info.py to pull fresh data")

        slot_ids.append(matches[0].id)

    return slot_ids


def set_node_name(slot_name: str, alias: str | None, is_item_link: bool) -> str:
    if alias:
        node_name = f"{alias}\n({slot_name})"
    elif is_item_link:
        node_name = f"item_link:\n{slot_name}"
    else:
        node_name = f"{slot_name}"
    return node_name


def main():
    parser = argparse.ArgumentParser(
        description="Create a hint graph of a room's hints. "
        "Graphs all unfound progression hints from all non-goaled slots by default. "
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
        help=argparse.SUPPRESS)
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
        "--show-found-hints",
        default=False,
        action="store_true",
        help="Show found hints. Warning: This can add a lot of bloat to the hint graph")
    parser.add_argument(
        "--show-goaled-slots",
        default=False,
        action="store_true",
        help="Show goaled slots")

    # TODO - Rename parents/children to finder/receiver?
    # Formal term is predecessor/successor

    hint_subgraph_group = parser.add_argument_group("Hint subgraph options. Shows all hints between all players in the subgraph (optional)")
    hint_subgraph_group.add_argument(
        "--hint-subgraph-slot",
        metavar="SLOT",
        help="Slot name of the slot the hint subgraph will be centered around. "
        "Requires one of the --[child-|parent-]depth options")
    hint_subgraph_group.add_argument(
        "--depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint subgraph to display in both directions. "
        "Requires the --hint-subgraph-slot option")
    hint_subgraph_group.add_argument(
        "--child-depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint subgraph to display for slots that depend on you. "
        "Requires the --hint-subgraph-slot option. Overrides --depth option")
    hint_subgraph_group.add_argument(
        "--parent-depth",
        metavar="DEPTH",
        type=int,
        help="Sets how deep in the hint subgraph to display for slots that you depend on. "
        "Requires the --hint-subgraph-slot option. Overrides --depth option")
    # TODO - Provide an option for the hint subgraph to show in edges, out edges or both?

    hint_chain_group = parser.add_argument_group("Hint chain options. Shows hints in a single direction for all selected players (optional)")
    hint_chain_group.add_argument(
        "-hcc", "--hint-chain-config",
        type=Path,
        metavar="FILE",
        help="Hint chain config file. See hint-chain-config-example.yaml for details")

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
        choices=["svg", "jpg", "png", "avif"],
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
        print("\tGeneral options:")
        print(f"\t\tdata-folder={args.data_folder}")
        print(f"\t\thighlight-slots={args.highlight_slots}")
        print(f"\t\tshow-entrances={args.show_entrances}")
        print(f"\t\tshow-found-hints={args.show_found_hints}")
        print(f"\t\tshow-goaled-slots={args.show_goaled_slots}")
        print("\tHint subgraph options:")
        print(f"\t\thint-subgraph-slot={args.hint_subgraph_slot}")
        print(f"\t\tdepth={args.depth}")
        print(f"\t\tchild-depth={args.child_depth}")
        print(f"\t\tparent-depth={args.parent_depth}")
        print("\tHint chain options:")
        print(f"\t\thint-chain-config={args.hint_chain_config}")
        print("\tOutput options:")
        print(f"\t\toutput-filename={args.output_filename}")
        print(f"\t\toutput-format={args.output_format}")
        print(f"\t\toutput-engine={args.output_engine}")
        print("")

    show_entrances: bool = args.show_entrances
    show_found_hints: bool = args.show_found_hints
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
    hint_subgraph_slot_provided: bool = args.hint_subgraph_slot is not None
    hint_subgraph_enabled: bool = depth_option_provided and hint_subgraph_slot_provided
    if depth_option_provided and not hint_subgraph_slot_provided:
        parser.error("The --hint-subgraph-slot argument is required when using --depth|--child-depth|--parent-depth")
    if hint_subgraph_slot_provided and not depth_option_provided:
        parser.error("At least one of the --depth|--child-depth|--parent-depth arguments are required "
                     "when using --hint-subgraph-slot")

    hint_chain_enabled: bool = args.hint_chain_config
    if hint_chain_enabled and hint_subgraph_enabled:
        parser.error("hint chain options and hint subgraph options were both enabled but only one can be enabled at a time. Only provide options for one or the other or none at all")

    hint_mode: HintMode = HintMode.HINT_GRAPH_MODE
    if hint_subgraph_enabled:
        hint_mode = HintMode.HINT_SUBGRAPH_MODE
    elif hint_chain_enabled:
        hint_mode = HintMode.HINT_CHAIN_MODE

    # TODO - Filter out nodes with >= some number of hints to find - Make this configurable
    # - Kinda broken. It filters out players that have high numbers of hints to find
    #   but when players that have hints to receive are looking for the slots that
    #   are sending them hints, these big slots get pulled in
    # - hint-subgraph-slot and depth options do a good job of reducing the noise of big
    #   slots so maybe just use that instead
    high_hint_count: int = 2147483647

    # Load required data from cached API data
    data_folder: str = args.data_folder
    room_data: RoomData = RoomData()
    room_data.load_room_data(data_folder)
    data_last_fetched = room_data.get_data_last_fetched()
    slot_mapping = room_data.get_slot_mapping()
    tracker = room_data.get_tracker()
    static_tracker = room_data.get_static_tracker()
    room_datapackages = room_data.get_room_datapackages()

    # Validate slot id if it was provided
    hint_subgraph_slot_id: int = -1

    # Validate slot name if it was provided
    hint_subgraph_slot_name: str | None = args.hint_subgraph_slot
    if hint_subgraph_slot_name:
        hint_subgraph_slot_id = get_slot_ids_from_names([hint_subgraph_slot_name], slot_mapping)[0]

    # Validate slot names to highlight exist
    highlight_slots: list[str] = args.highlight_slots
    slot_ids_to_highlight: list[int] = get_slot_ids_from_names(highlight_slots, slot_mapping)

    # Create output filename
    fetch_time: str = data_last_fetched["data_last_fetched"]
    output_filename: Path = Path(f"{fetch_time}")
    if args.output_filename is not None:
        output_filename = Path(get_file_safe_name(f"{output_filename}_{args.output_filename}"))

    if debug:
        print("Just after argument validation")
        print(f"\tdata_folder={data_folder}")
        print(f"\thighlight_slots={highlight_slots}")
        print(f"\tshow_entrances={show_entrances}")
        print(f"\tshow_found_hints={show_found_hints}")
        print(f"\tshow_goaled_slots={show_goaled_slots}")
        print(f"\thint_subgraph_slot={hint_subgraph_slot_name}")
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
    action_string: str = "Creating progression hint"
    if depth_option_provided:
        action_string += f" subgraph for slot {slot_mapping[hint_subgraph_slot_id-1].name} showing"
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

    if show_found_hints:
        action_string += "\n- And showing found hints"

    if show_goaled_slots:
        action_string += "\n- And showing goaled slots"

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
    for idx, player in enumerate(slot_mapping):
        if len(player.item_link_members) == 0:
            hints_processed.append(PlayerHints(
                player_num=tracker["aliases"][idx]["player"],
                slot_name=player.name,
                game=player.game,
                alias=tracker["aliases"][idx]["alias"],
                has_goaled=tracker["player_status"][idx]["status"] == 30,
                hints_to_find=[],
                hints_for_others=[],
                has_hint=False,
                is_item_link=False,
                node_name=set_node_name(slot_name=player.name, alias=tracker["aliases"][idx]["alias"], is_item_link=False)
            ))
        else:
            hints_processed.append(PlayerHints(
                player_num=player.id,
                slot_name=player.name,
                game=player.game,
                alias=None,
                has_goaled=False,
                hints_to_find=[],
                hints_for_others=[],
                has_hint=False,
                is_item_link=True,
                node_name=set_node_name(slot_name=player.name, alias=None, is_item_link=True)
            ))

    if debug:
        with open(f"{data_folder}/make-hint-graph-debug/hints_processed_pre.json", "w") as f:
            json.dump([asdict(hint) for hint in hints_processed], f, indent=3)

    # TODO - When processing item_links, connect them to the slots they represent
    # - item_link slot will be finder, slots in the group will be the receiver
    # Add hints to hints_processed
    for hint in hints_raw_unique:
        # Skip hints that were found
        if not show_found_hints and hint.found:
            continue

        # TODO - Eventually make this configurable
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
            location_name=location[0],
            item_name=item[0],
            found=hint.found,
            entrance=hint.entrance,
            item_flags=hint.item_flags,
            status=hint.status
        ))
        hints_processed[hint.receiving_player].hints_for_others.append(HintProcessed(
            finding_player=hint.finding_player,
            receiving_player=hint.receiving_player,
            location_name=location[0],
            item_name=item[0],
            found=hint.found,
            entrance=hint.entrance,
            item_flags=hint.item_flags,
            status=hint.status
        ))
        hints_processed[hint.receiving_player].has_hint = True
        hints_processed[hint.finding_player].has_hint = True

    # TODO - Make this better. Probably want to really think about the format of hints_processed.json
    # TODO - Also probably add a hint_last_processed metadata file so we know if we need to process hints in the first place
    with open(f"{data_folder}/hints_processed.json", "w") as f:
        if debug:
            json.dump([asdict(hint) for hint in hints_processed], f, indent=3)
        else:
            json.dump([asdict(hint) for hint in hints_processed], f)

    # Create list of nodes to show
    visited_nodes: set[int] = set()

    # Show all nodes if we're not looking for a specific subgraph. Also remove the special Archipelago server slot 0 from the list
    if not show_child_nodes and not show_parent_nodes:
        visited_nodes.update([node.player_num for node in hints_processed if node.player_num != 0])

    # Show nodes that depend on us
    if show_child_nodes:
        nodes_to_visit: list[PlayerHints] = [hints_processed[hint_subgraph_slot_id]]
        nodes_next_loop: list[PlayerHints] = []
        visited_nodes_child: set[int] = set([hints_processed[hint_subgraph_slot_id].player_num])
        while child_depth > 0:
            while nodes_to_visit:
                current_node = nodes_to_visit.pop()
                for hint in current_node.hints_to_find:
                    if hint.receiving_player not in visited_nodes_child:
                        visited_nodes_child.add(hint.receiving_player)
                        nodes_next_loop.append(hints_processed[hint.receiving_player])
            # Reset for the next depth
            nodes_to_visit = nodes_next_loop
            nodes_next_loop = []
            child_depth -= 1
        visited_nodes.update(visited_nodes_child)

    # Show nodes that we depend on
    if show_parent_nodes:
        nodes_to_visit: list[PlayerHints] = [hints_processed[hint_subgraph_slot_id]]
        nodes_next_loop: list[PlayerHints] = []
        visited_nodes_parent: set[int] = set([hints_processed[hint_subgraph_slot_id].player_num])
        while parent_depth > 0:
            while nodes_to_visit:
                current_node = nodes_to_visit.pop()
                for hint in current_node.hints_for_others:
                    if hint.finding_player not in visited_nodes_parent:
                        visited_nodes_parent.add(hint.finding_player)
                        nodes_next_loop.append(hints_processed[hint.finding_player])

            # Reset for the next depth
            nodes_to_visit = nodes_next_loop
            nodes_next_loop = []
            parent_depth -= 1
        visited_nodes.update(visited_nodes_parent)

    # Create the graph
    dot = pygraphviz.AGraph(directed=True, rankdir='LR', strict=False)

    # Highlight nodes if they are called out even if they won't connect to the graph with current settings
    if slot_ids_to_highlight:
        for slot_id in slot_ids_to_highlight:
            dot.add_node(f"{hints_processed[slot_id].player_num}",
                         label=hints_processed[slot_id].node_name,
                         color="darkgreen",
                         fillcolor="darkgreen",
                         style="filled",
                         fontcolor="white")

    if hint_mode is HintMode.HINT_GRAPH_MODE or hint_mode is HintMode.HINT_SUBGRAPH_MODE:
        # TODO - Merge multiple hints to the same slot into a single edge? (should speed things up)
        # Show the full graph/subgraph for all the nodes selected
        for index in visited_nodes:
            player = hints_processed[index]
            if player.has_hint:
                dot.add_node(f"{player.player_num}", label=player.node_name)
                for hint in player.hints_to_find:
                    if hint.finding_player in visited_nodes and hint.receiving_player in visited_nodes:
                        label = f"{hint.item_name} at\n{hint.location_name}"
                        if hint.entrance and show_entrances:
                            label = f"{label}\n({hint.entrance})"
                        dot.add_edge(u=f"{hint.finding_player}",
                                    v=f"{hint.receiving_player}",
                                    label=label)

    # Hint chains!
    elif hint_mode is HintMode.HINT_CHAIN_MODE:
        print()
        print("Making hint chain!")
        print()

        # TODO - Raise a RuntimeError or something if this fails to validate
        def validate_hint_chain_yaml(hint_chain_data):
            pass

        with open(args.hint_chain_config, "r") as f:
            hint_chain_data: dict[str, list] = yaml.safe_load(f)
            validate_hint_chain_yaml(hint_chain_data)

        hint_chain_config: dict[str, list[HintChainConfig]] = {
            key: [HintChainConfig(**datum) for datum in list_data]
            for key, list_data in hint_chain_data.items()
        }

        for chain in hint_chain_config["hint_chains"]:
            print(f"Processing hint chain {chain.name} for slots {chain.hint_chain} in direction {chain.direction}. search_last_slot={chain.search_last_slot}")
            hint_chain_slot_ids: list[int] = get_slot_ids_from_names(chain.hint_chain, slot_mapping)
            print(f"\thint_chain_slot_ids={hint_chain_slot_ids}")

            # TODO - Need to iterate down the chain instead of just looking at the first one
            hint_chain_start_slot_id: int = hint_chain_slot_ids[0]

            dot.add_node(f"{hints_processed[hint_chain_start_slot_id].player_num}",
                        label=hints_processed[hint_chain_start_slot_id].node_name)

            visited_nodes: set[int] = set()

            # TODO - Need to look for the specific receiver slot
            if chain.direction == HintChainDirection.RECEIVER:
                parent_depth = 1 # TODO - This has to come from somewhere?
                nodes_to_visit: list[PlayerHints] = [hints_processed[hint_chain_start_slot_id]]
                nodes_next_loop: list[PlayerHints] = []
                visited_nodes_parent: set[int] = set([hints_processed[hint_chain_start_slot_id].player_num])
                while parent_depth > 0:
                    while nodes_to_visit:
                        current_node = nodes_to_visit.pop()
                        for hint in current_node.hints_for_others:
                            if hint.finding_player not in visited_nodes_parent:
                                visited_nodes_parent.add(hint.finding_player)
                                nodes_next_loop.append(hints_processed[hint.finding_player])

                    # Reset for the next depth
                    nodes_to_visit = nodes_next_loop
                    nodes_next_loop = []
                    parent_depth -= 1
                visited_nodes.update(visited_nodes_parent)

            # TODO - Need to look for the specific finder slot
            if chain.direction == HintChainDirection.FINDER:
                child_depth = 1 # TODO - This has to come from somewhere?
                nodes_to_visit: list[PlayerHints] = [hints_processed[hint_chain_start_slot_id]]
                nodes_next_loop: list[PlayerHints] = []
                visited_nodes_child: set[int] = set([hints_processed[hint_chain_start_slot_id].player_num])
                while child_depth > 0:
                    while nodes_to_visit:
                        current_node = nodes_to_visit.pop()
                        for hint in current_node.hints_to_find:
                            if hint.receiving_player not in visited_nodes_child:
                                visited_nodes_child.add(hint.receiving_player)
                                nodes_next_loop.append(hints_processed[hint.receiving_player])
                    # Reset for the next depth
                    nodes_to_visit = nodes_next_loop
                    nodes_next_loop = []
                    child_depth -= 1
                visited_nodes.update(visited_nodes_child)

            # TODO - Need to verify if self hints work

            # Need to have a base node and then look for hints to the nodes that we want to connect to
            # This probably needs to be done iteratively as we're discovering the hint chain
            for index in visited_nodes:
                player = hints_processed[index]
                if player.has_hint:
                    dot.add_node(f"{player.player_num}", label=player.node_name)

                    hints_to_search: list[HintProcessed] = []
                    if chain.direction == HintChainDirection.FINDER:
                        hints_to_search = player.hints_for_others
                    elif chain.direction == HintChainDirection.RECEIVER:
                        hints_to_search = player.hints_to_find

                    for hint in hints_to_search:
                        add_hint: bool = False
                        if chain.direction == HintChainDirection.FINDER:
                            add_hint = hint.finding_player == hint_chain_start_slot_id and hint.receiving_player in visited_nodes
                        elif chain.direction == HintChainDirection.RECEIVER:
                            add_hint = hint.receiving_player == hint_chain_start_slot_id and hint.finding_player in visited_nodes

                        if add_hint:
                            label = f"{hint.item_name} at\n{hint.location_name}"
                            if hint.entrance and show_entrances:
                                label = f"{label}\n({hint.entrance})"
                            dot.add_edge(u=f"{hint.finding_player}",
                                        v=f"{hint.receiving_player}",
                                        label=label)

            print()





        # print(f"\t\thint-chain-start-slot={args.hint_chain_start_slot}")
        # print(f"\t\thint-chain-direction={args.hint_chain_direction}")
        # print(f"\t\thint-chain-parent-slots={args.hint_chain_parent_slots}")
        # print(f"\t\thint-chain-child-slots={args.hint_chain_child_slots}")

    # Add item_link edges to all members in the group
    for item_link in static_tracker["groups"]:
        if dot.has_node(item_link["slot"]):
            for member in item_link["members"]:
                if dot.has_node(member):
                    dot.add_edge(u=f"{item_link["slot"]}",
                                 v=f"{member}",
                                 label=f"{item_link["name"]} item_link")

    print(f"Number of players={dot.number_of_nodes()}")
    print(f"Number of hints={dot.number_of_edges()}")

    # Save it!
    output_file: str = f"{data_folder}/graphs/{output_filename}.{output_format}"
    print(f"Saving to {output_file}")
    Path(f"{data_folder}/graphs/dot").mkdir(parents=True, exist_ok=True)
    dot.write(f"{data_folder}/graphs/dot/{output_filename}.dot")

    start_time = time.perf_counter()
    if output_format == "avif":
        jpg_data = dot.draw(format="jpg", prog=output_engine, args="-v")
        with Image.open(io.BytesIO(jpg_data)) as image:
            image.save(output_file)
    # TODO - Configure png to save it smaller
    else:
        dot.draw(path=output_file, format=output_format, prog=output_engine, args="-v")
    end_time = time.perf_counter()

    execution_time = end_time - start_time
    print(f"Hint graph creation took {execution_time:.6f} seconds to run")


if __name__ == "__main__":
    main()
