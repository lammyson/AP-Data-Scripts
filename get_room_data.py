import argparse
import asyncio
import httpx
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def get_file_safe_name(name: str) -> str:
    return "".join(c for c in name if c not in '<>:"/\\|?*')


class GetRoomData():
    _room_suuid: str
    _output_folder: Path
    _debug = False

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

    def _parse_arguments(self):
        parser = argparse.ArgumentParser(description="Downloads data from an Archipelago room")
        parser.add_argument(
            "-r", "--room-suuid",
            type=str,
            required=True,
            help="Room SUUID. This is a string found in your room's URL. Example: https://archipelago.gg/<ROOM_SUUID>")
        parser.add_argument(
            "-f", "--output-folder",
            type=str,
            required=True,
            help="Output folder. This is where all json files and graphs will be written")
        parser.add_argument(
            "-d", "--debug",
            default=False,
            action="store_true",
            help="Print debug statements and files")
        args = parser.parse_args()

        self._room_suuid = args.room_suuid
        self._output_folder = args.output_folder
        self._debug = args.debug

    async def download_room_data(self, room_suuid: str, output_folder: Path, debug: bool = False):
        self._room_suuid = room_suuid
        self._output_folder = output_folder
        self._debug = debug

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

        print(f"Using room_suuid={room_suuid}")

        # Verify the output folder is for the requested room
        if room_suuid and Path(f"{output_folder}/suuids.json").is_file():
            with open(f"{output_folder}/suuids.json", "r") as f:
                suuids = json.load(f)
            if "room_suuid" in suuids and suuids["room_suuid"] != room_suuid:
                print(f"Provided room_suuid={room_suuid} does not match "
                      f"the {output_folder}/suuids.json room_suuid={suuids["room_suuid"]}. "
                      f"Please choose a different folder or delete {output_folder}/suuids.json "
                      "if you want to use the existing folder")
                exit(1)

        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=60) as client:
            # /room_status/<suuid:room_id>
            # Cache timer: None
            room_status = await self._download_from_endpoint_to_file(
                endpoint=f"room_status/{room_suuid}",
                endpoint_pretty_name="room_status",
                file=Path(f"{output_folder}/room_status.json"),
                client=client,
                semaphore=sem)
            tracker_suuid = room_status["tracker"]

            # Verify the tracker suuid matches
            if tracker_suuid and Path(f"{output_folder}/suuids.json").is_file():
                with open(f"{output_folder}/suuids.json", "r") as f:
                    suuids = json.load(f)
                if "tracker_suuid" in suuids and suuids["tracker_suuid"] != tracker_suuid:
                    print(f"Provided tracker_suuid={tracker_suuid} does not match "
                          f"the {output_folder}/suuids.json tracker_suuid={suuids["tracker_suuid"]}. "
                          f"Please choose a different folder or delete {output_folder}/suuids.json "
                          "if you want to use the existing folder")
                    exit(1)

            suuids = {
                "room_suuid": room_suuid,
                "tracker_suuid": tracker_suuid
            }
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
            room_suuid=self._room_suuid,
            output_folder=self._output_folder,
            debug=self._debug)


if __name__ == "__main__":
    asyncio.run(GetRoomData()._main())
