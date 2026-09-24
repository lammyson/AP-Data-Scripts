import argparse
from bs4 import BeautifulSoup
import asyncio
import httpx
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def get_file_safe_name(name: str) -> str:
    return "".join(c for c in name if c not in '<>:"/\\|?*')


class GetRoomData():
    _room_suuid: str | None = None
    _tracker_suuid: str | None = None
    _output_folder: Path
    _debug = False
    _suuids: dict[str, str] = {}

    async def _download_from_endpoint_to_file(
            self,
            endpoint: str,
            endpoint_pretty_name: str,
            file: Path,
            client: httpx.AsyncClient,
            semaphore: asyncio.Semaphore) -> dict[str, Any]:
        async with semaphore:
            if self._debug:
                print(f"Requesting {endpoint_pretty_name} https://archipelago.gg/api/{endpoint}")
            response: httpx.Response = await client.get(f"https://archipelago.gg/api/{endpoint}")
            response.raise_for_status()

            with open(file, "w") as f:
                json.dump(response.json(), f)
                print(f"Wrote {endpoint_pretty_name} to {file}")

            return response.json()

    async def _download_from_html_to_file(
            self,
            endpoint: str,
            endpoint_pretty_name: str,
            file: Path,
            client: httpx.AsyncClient,
            semaphore: asyncio.Semaphore) -> str:
        async with semaphore:
            if self._debug:
                print(f"Requesting {endpoint_pretty_name} https://archipelago.gg/{endpoint}")
            response: httpx.Response = await client.get(f"https://archipelago.gg/{endpoint}")
            response.raise_for_status()

            if self._debug:
                Path(f"{self._output_folder}/get_room_data_debug").mkdir(parents=True, exist_ok=True)
                with open(file, "w", encoding="utf-8") as f:
                    f.write(response.text)
                    print(f"Wrote {endpoint_pretty_name} to {file}")

            return response.text

    def _parse_tracker_checks_table(self, tracker_html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(markup=tracker_html, features="html.parser")
        checks_table_html = soup.find("table", id="checks-table")
        if checks_table_html is None or len(checks_table_html) == 0:
            raise KeyError("table tag with id=check-table attribute not found in tracker html")

        header_row = checks_table_html.find_all("th")
        if header_row is None or len(header_row) == 0:
            raise KeyError("th tag not found in checks-table")

        header_text: list[str] = [header_text.get_text(separator=" ") for header_text in header_row]
        if len(header_text) == 0:
            raise RuntimeError("checks-table did not have any header text")

        table_body = checks_table_html.find("tbody")
        if table_body is None or len(table_body) == 0:
            raise KeyError("tbody tag not found in checks-table")

        table_flat_data = table_body.find_all("td")
        if table_flat_data is None or len(table_flat_data) == 0:
            raise KeyError("td tag not found in checks-table tbody")
        if len(table_flat_data) % len(header_text) != 0:
            raise RuntimeError("checks-table does not have expected amount of data")

        num_cols = len(header_text)
        row_data = [table_flat_data[i:i+num_cols] for i in range(0, len(table_flat_data), num_cols)]
        checks_table: list[dict[str, Any]] = []
        for row in row_data:
            checks_table.append({
                header_text[0]: row[0].get_text().strip(),
                header_text[1]: row[1].get_text(),
                header_text[2]: row[2].get_text(),
                header_text[3]: row[3].get_text().strip(),
                header_text[4]: row[4].get_text().strip(),
                header_text[5]: row[5].get_text().strip(),
                header_text[6]: row[6].get_text(),
            })

        if self._debug:
            Path(f"{self._output_folder}/get_room_data_debug").mkdir(parents=True, exist_ok=True)
            with open(f"{self._output_folder}/get_room_data_debug/checks_table.json", "w") as f:
                json.dump(checks_table, f, indent=3)
                print(f"Wrote tracker html checks-table to {self._output_folder}/checks_table.json")

        return checks_table

    def _room_status_to_players_json(self, room_status: dict[str, Any]):
        players = [
            {
                "name": player_data[0],
                "game": player_data[1]
            }
            for player_data in room_status["players"]
        ]
        file = f"{self._output_folder}/players.json"
        with open(file, "w") as f:
            json.dump(players, f)
            print(f"Wrote players/games to {file}")

    def _checks_table_to_players_json(self, checks_table: list[dict[str, Any]]):
        players = [
            {
                "name": row["Name"],
                "game": row["Game"]
            }
            for row in checks_table
        ]
        file = f"{self._output_folder}/players.json"
        with open(file, "w") as f:
            json.dump(players, f)
            print(f"Wrote players/games to {file}")

    def _load_suuids(self) -> dict[str, str]:
        if self._suuids:
            pass
        elif Path(f"{self._output_folder}/suuids.json").is_file():
            with open(f"{self._output_folder}/suuids.json", "r") as f:
                self._suuids = json.load(f)
        return self._suuids

    def _verify_room_suuid(self, room_suuid: str | None):
        suuids = self._load_suuids()
        if room_suuid and suuids:
            if "room_suuid" in suuids and suuids["room_suuid"] != room_suuid:
                print(f"Provided room_suuid={room_suuid} does not match "
                      f"the {self._output_folder}/suuids.json room_suuid={suuids["room_suuid"]}. "
                      f"Please choose a different folder or delete {self._output_folder}/suuids.json "
                      "if you want to use the existing folder")
                exit(1)

    def _verify_tracker_suuid(self, tracker_suuid: str | None):
        suuids = self._load_suuids()
        if tracker_suuid and suuids:
            if "tracker_suuid" in suuids and suuids["tracker_suuid"] != tracker_suuid:
                print(f"Provided tracker_suuid={tracker_suuid} does not match "
                    f"the {self._output_folder}/suuids.json tracker_suuid={suuids["tracker_suuid"]}. "
                    f"Please choose a different folder or delete {self._output_folder}/suuids.json "
                    "if you want to use the existing folder")
                exit(1)

    def _parse_arguments(self):
        parser = argparse.ArgumentParser(description="Downloads data from an Archipelago room")
        suuid_arg_group = parser.add_argument_group(
            "suuid options",
            description="Use these arguments to pass in a suuid. Only one of these are required"
            ).add_mutually_exclusive_group(required=True)
        suuid_arg_group.add_argument(
            "-r", "--room-suuid",
            type=str,
            help="Room SUUID. This is a string found in your room's URL. Example: https://archipelago.gg/room/<ROOM_SUUID>")
        suuid_arg_group.add_argument(
            "-t", "--tracker-suuid",
            type=str,
            help="Tracker SUUID. This is a string found in your room's tracker's URL. Example: https://archipelago.gg/tracker/<TRACKER_SUUID>")
        parser.add_argument(
            "-f", "--output-folder",
            type=str,
            required=True,
            help="Output folder. This is where all room specific data will be written")
        parser.add_argument(
            "-d", "--debug",
            default=False,
            action="store_true",
            help="Print debug statements and files")
        args = parser.parse_args()

        self._room_suuid = args.room_suuid
        self._tracker_suuid = args.tracker_suuid
        self._output_folder = args.output_folder
        self._debug = args.debug

    async def download_room_data(self, output_folder: Path, room_suuid: str | None = None, tracker_suuid: str | None = None, debug: bool = False):
        self._room_suuid = room_suuid
        self._tracker_suuid = tracker_suuid
        self._output_folder = output_folder
        self._debug = debug

        # Verify only one suuid argument is set
        if (room_suuid is None) == (tracker_suuid is None):
            raise ValueError("Only one of room_suuid or tracker_suuid must be defined")

        # Create output folder and get the current time
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        Path(".datapackages").mkdir(parents=True, exist_ok=True)
        now_time = datetime.now(tz=timezone.utc)

        # Verify the time the data was last fetched so that we don't request data too quickly
        cache_timeout_s = 1800
        if Path(f"{output_folder}/last_fetched.json").is_file():
            with open(f"{output_folder}/last_fetched.json", "r") as f:
                last_fetched = json.load(f)
            if "last_fetched" in last_fetched:
                old_time = datetime.strptime(last_fetched["last_fetched"], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                if (now_time - old_time).seconds <= cache_timeout_s:
                    print(f"Data was last downloaded {(now_time - old_time).seconds} seconds ago "
                          f"which is less than the {cache_timeout_s} second ({cache_timeout_s/60:g} minute) cache timer. "
                          "Not downloading room data")
                    exit(0)

        if room_suuid:
            print(f"Using room_suuid={room_suuid}")
            self._verify_room_suuid(room_suuid)
        else:
            print(f"Using tracker_suuid={tracker_suuid}")
            self._verify_tracker_suuid(tracker_suuid)

        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=60) as client:
            if room_suuid:
                # /room_status/<suuid:room_id>
                # Cache timer: None
                room_status = await self._download_from_endpoint_to_file(
                    endpoint=f"room_status/{room_suuid}",
                    endpoint_pretty_name="room_status",
                    file=Path(f"{output_folder}/room_status.json"),
                    client=client,
                    semaphore=sem)
                tracker_suuid = room_status["tracker"]
                self._verify_tracker_suuid(tracker_suuid)
                self._room_status_to_players_json(room_status=room_status)
            else:
                tracker_html = await self._download_from_html_to_file(
                    endpoint=f"tracker/{tracker_suuid}",
                    endpoint_pretty_name="tracker html",
                    file=Path(f"{output_folder}/get_room_data_debug/tracker.html"),
                    client=client,
                    semaphore=sem)
                checks_table: list[dict[str, Any]] = self._parse_tracker_checks_table(tracker_html=tracker_html)
                self._checks_table_to_players_json(checks_table=checks_table)

            suuids = {}
            if room_suuid:
                suuids.update({"room_suuid": room_suuid})
            if tracker_suuid:
                suuids.update({"tracker_suuid": tracker_suuid})
            with open(f"{output_folder}/suuids.json", "w") as f:
                json.dump(suuids, f)
                print(f"Wrote suuids to {output_folder}/suuids.json")

            async with asyncio.TaskGroup() as tg:
                # /tracker/<suuid:tracker>
                # Cache timer: 60 seconds
                tg.create_task(self._download_from_endpoint_to_file(
                    endpoint=f"tracker/{tracker_suuid}",
                    endpoint_pretty_name="tracker",
                    file=Path(f"{output_folder}/tracker.json"),
                    client=client,
                    semaphore=sem))

                # /static_tracker/<suuid:tracker>
                # Cache timer: 300 seconds
                static_tracker_task = tg.create_task(self._download_from_endpoint_to_file(
                    endpoint=f"static_tracker/{tracker_suuid}",
                    endpoint_pretty_name="static_tracker",
                    file=Path(f"{output_folder}/static_tracker.json"),
                    client=client,
                    semaphore=sem))

                # /slot_data_tracker/<suuid:tracker>
                # Cache timer: 300 seconds
                tg.create_task(self._download_from_endpoint_to_file(
                    endpoint=f"slot_data_tracker/{tracker_suuid}",
                    endpoint_pretty_name="slot_data_tracker",
                    file=Path(f"{output_folder}/slot_data_tracker.json"),
                    client=client,
                    semaphore=sem))

            static_tracker = static_tracker_task.result()

            # /datapackage/<string:checksum>
            # Cache timer: None
            async with asyncio.TaskGroup() as tg:
                for game, data in static_tracker["datapackage"].items():
                    safe_game_name: str = get_file_safe_name(game)
                    checksum: str = data["checksum"]
                    game_folder = Path(f".datapackages/{safe_game_name}")
                    datapackage_file = Path(f"{game_folder}/{checksum}.json")
                    if not datapackage_file.is_file():
                        Path.mkdir(game_folder, parents=True, exist_ok=True)
                        tg.create_task(self._download_from_endpoint_to_file(
                            endpoint=f"datapackage/{checksum}",
                            endpoint_pretty_name=f"{game} datapackage",
                            file=datapackage_file,
                            client=client,
                            semaphore=sem))

        last_fetched_json = {"last_fetched": datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")}
        with open(f"{output_folder}/last_fetched.json", "w") as f:
            json.dump(last_fetched_json, f)
            print(f"Wrote last_fetched to {output_folder}/last_fetched.json")

    async def _main(self):
        self._parse_arguments()
        await self.download_room_data(
            output_folder=self._output_folder,
            room_suuid=self._room_suuid,
            tracker_suuid=self._tracker_suuid,
            debug=self._debug)


if __name__ == "__main__":
    asyncio.run(GetRoomData()._main())
