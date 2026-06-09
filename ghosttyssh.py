#!/usr/bin/env python3
"""
ghosttyssh - SSH wrapper for Ghostty terminfo setup + saved hosts TUI
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

CONFIG_DIR = Path.home() / ".config" / "ghosttyssh"
HOSTS_FILE = CONFIG_DIR / "hosts.json"


@dataclass
class Host:
    name: str
    target: str


class HostStore:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if not HOSTS_FILE.exists():
            HOSTS_FILE.write_text("[]")

    def load(self) -> List[Host]:
        try:
            data = json.loads(HOSTS_FILE.read_text())
            return [Host(**item) for item in data]
        except Exception:
            return []

    def save(self, hosts: List[Host]):
        HOSTS_FILE.write_text(
            json.dumps([asdict(h) for h in hosts], indent=2)
        )

    def find_by_target(self, target: str) -> Optional[Host]:
        for host in self.load():
            if host.target == target:
                return host
        return None

    def add(self, host: Host):
        hosts = self.load()

        for existing in hosts:
            if existing.target == host.target:
                return

        hosts.append(host)
        self.save(hosts)


store = HostStore()


def parse_target(args: List[str]) -> Optional[str]:
    if not args:
        return None

    if args[0] == "ssh":
        args = args[1:]

    if not args:
        return None

    return " ".join(args)


def ensure_ghostty_terminfo(target: str):
    cmd = f"infocmp ghostty | ssh {target} 'tic -x -'"

    print(f"\n→ Installing Ghostty terminfo:\n   {cmd}\n")

    result = subprocess.run(cmd, shell=True)

    if result.returncode != 0:
        sys.exit(result.returncode)


def ssh_into_host(target: str):
    env = os.environ.copy()

    # Use a minimal TERM that defines the backspace key (kbs) but lacks
    # mouse-reporting (kmous) so we don't get escape-sequence spam when
    # the mouse moves.  vt220 is universally available on remote hosts.
    env["TERM"] = "vt220"

    print(f"\n→ Connecting to {target}\n")

    os.execvpe(
        "ssh",
        ["ssh"] + shlex.split(target),
        env,
    )


class Picker:
    def __init__(self, hosts: List[Host]):
        self.hosts = hosts

    def run(self) -> Optional[str]:
        try:
            from textual.app import App, ComposeResult
            from textual.containers import Container
            from textual.widgets import (
                Footer,
                Header,
                Label,
                ListItem,
                ListView,
            )
        except ImportError:
            print("Install dependencies:")
            print("  pip install textual rich")
            sys.exit(1)

        selected = {"target": None}
        hosts = self.hosts

        class HostPicker(App):
            CSS = """
            Screen {
                align: center middle;
            }

            #box {
                width: 70;
                height: 24;
                border: round cyan;
            }

            ListView {
                height: 1fr;
            }
            """

            BINDINGS = [
                ("q",           "quit", "Quit"),
                *[
                    (str(d), f"select({d})", f"Select #{d}")
                    for d in range(10)
                ],
            ]

            def compose(self):
                yield Header()

                with Container(id="box"):
                    yield ListView(
                        *[
                            ListItem(Label(f" [{i}]   {host.name}    {host.target}"))
                            for i, host in enumerate(hosts)
                        ]
                    )

                yield Footer()

            def on_list_view_selected(self, event):
                idx = event.list_view.index
                selected["target"] = hosts[idx].target
                self.exit()

            def action_select(self, digit: int) -> None:
                """Select host by digit shortcut (0-9)."""
                if digit < len(hosts):
                    selected["target"] = hosts[digit].target
                    self.exit()

        app = HostPicker()
        app.run()

        return selected["target"]


def maybe_save_host(target: str):
    existing = store.find_by_target(target)

    if existing:
        return

    print(f"\nNew host detected: {target}")

    answer = input("Save this host? [Y/n]: ").strip().lower()

    if answer in ("", "y", "yes"):
        name = input("Friendly name: ").strip()

        if not name:
            name = target

        store.add(Host(name=name, target=target))

        print(f"Saved '{name}' → {target}\n")


def main():
    target = parse_target(sys.argv[1:])

    if not target:
        hosts = store.load()

        if not hosts:
            print("No saved hosts.")
            print("Usage:")
            print("  ghosttyssh ssh yourhost")
            sys.exit(1)

        target = Picker(hosts).run()

        if not target:
            sys.exit(0)

    maybe_save_host(target)

    ensure_ghostty_terminfo(target)
    ssh_into_host(target)


if __name__ == "__main__":
    main()

