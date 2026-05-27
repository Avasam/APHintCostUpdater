from __future__ import annotations

import asyncio
import math
import re
import urllib.parse

from archipelagopy import packets
from archipelagopy.client import Client
from archipelagopy.packets import Connect
from archipelagopy.packets.client.say import Say
from tap import Tap

INITIAL_HINT_COST = 50
STATUS_RE = re.compile(r"\((\d+)/(\d+)\)")

def compute_hint_cost(status_lines: list[str]) -> int:
    checks_done = checks_total = 0
    for line in status_lines:
        if m := STATUS_RE.search(line):
            checks_done += int(m.group(1))
            checks_total += int(m.group(2))
    if not checks_total:
        raise ValueError(f"No status data parsed from {len(status_lines)} lines")
    return math.floor((1 - checks_done / checks_total) * INITIAL_HINT_COST)


class HintCostClient(Client):
    def __init__(
        self,
        host: str,
        port: int,
        slot_name: str,
        password: str | None,
        *,
        secure: bool,
    ):
        super().__init__(host=host, port=port, secure=secure)
        self.slot_name = slot_name
        self.password = password
        self.hint_cost: int | None = None
        self._connected = asyncio.Event()
        self._status_lines: list[str] = []

    async def on_room_info(self, packet: packets.RoomInfo):
        self.hint_cost = packet.hint_cost
        await self.send(
            Connect(
                version=packet.version,
                tags=["TextOnly"],
                name=self.slot_name,
                password=self.password or "",
            )
        )

    async def on_connected(self, packet: packets.Connected):
        self._connected.set()

    async def on_connection_refused(self, packet: packets.ConnectionRefused):
        print("Connection refused:", packet.errors)
        await self.stop()

    async def on_print_json(self, packet: packets.PrintJSON):
        text = "".join(part.text or "" for part in packet.data)
        self._status_lines.append(text)


async def run(args: Args):
    parsed = urllib.parse.urlparse(
        args.host if "://" in args.host else f"https://{args.host}"
    )
    # This should be impossible as we expect "archipelago.gg:12345"

    assert parsed.hostname
    assert parsed.port

    async with HintCostClient(
        parsed.hostname,
        parsed.port,
        args.slot_name,
        args.password,
        secure=parsed.scheme == "https",
    ) as client:
        async with asyncio.timeout(30):
            await client._connected.wait()

        await client.send(Say(text="!status"))
        await asyncio.sleep(2)

        new_cost = compute_hint_cost(client._status_lines)

        print("current hint cost:", client.hint_cost)
        print("new hint cost:", new_cost)

        if not args.dry_run:
            await client.send(Say(text=f"!admin login {args.password}"))
            await asyncio.sleep(1)
            await client.send(Say(text=f"!admin /option hint_cost {new_cost}"))
            await asyncio.sleep(1)


class Args(Tap):
    host: str
    slot_name: str
    password: str | None = None
    dry_run: bool = False
    """Print new cost without applying it"""

    def configure(self) -> None:
        self.add_argument("host")
        self.add_argument("slot_name")
        self.add_argument("password", nargs="?", default=None)


if __name__ == "__main__":
    asyncio.run(run(Args().parse_args()))
