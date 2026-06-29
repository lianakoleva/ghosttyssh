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


def ssh_into_host(target: str, friendly_name: str = ""):
    env = os.environ.copy()

    # Use a minimal TERM that defines the backspace key (kbs) but lacks
    # mouse-reporting (kmous) so we don't get escape-sequence spam when
    # the mouse moves.  vt220 is universally available on remote hosts.
    env["TERM"] = "vt220"

    if friendly_name:
        print(f"\033]0;{friendly_name}\007", end="", flush=True)

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
            from textual.binding import Binding
            from textual.containers import Container
            from textual.screen import ModalScreen
            from textual.widgets import (
                Button,
                Footer,
                Header,
                Input,
                Label,
                ListItem,
                ListView,
            )
        except ImportError:
            print("Install dependencies:")
            print("  pip install textual rich")
            sys.exit(1)

        class AddHostScreen(ModalScreen[str]):
            """Modal screen to add a new host connection."""

            BINDINGS = [("escape", "cancel", "Cancel")]

            DEFAULT_CSS = """
            AddHostScreen {
                align: center middle;
            }

            #add-dialog {
                width: 60;
                height: auto;
                border: thick $accent;
                background: $surface;
                padding: 1 2;
            }

            #add-dialog Label {
                width: 100%;
                margin: 1 0 0 0;
            }

            #add-dialog Input {
                width: 100%;
                margin: 0 0 1 0;
            }

            #add-dialog #btn-row {
                width: 100%;
                align: right middle;
                height: auto;
                margin: 1 0 0 0;
            }

            #add-dialog Button {
                margin: 0 0 0 1;
            }
            """

            def compose(self):
                with Container(id="add-dialog"):
                    yield Label("[bold]Target:[/bold]  (e.g. user@host)")
                    yield Input(placeholder="SSH target", id="target-input")
                    yield Label("[bold]Friendly Name:[/bold]  (optional)")
                    yield Input(placeholder="My Server", id="name-input")
                    with Container(id="btn-row"):
                        yield Button("Cancel", variant="default", id="cancel-btn")
                        yield Button("[bold]Add[/bold]", variant="primary", id="add-btn")

            def action_cancel(self):
                self.dismiss("")

            def on_button_pressed(self, event: Button.Pressed):
                if event.button.id == "add-btn":
                    target = self.query_one("#target-input", Input).value.strip()
                    name = self.query_one("#name-input", Input).value.strip()
                    if target:
                        if not name:
                            name = target
                        self.dismiss(json.dumps({"target": target, "name": name}))
                    else:
                        self.notify("Target is required.", severity="error")
                else:
                    self.dismiss("")

        class ConfirmDeleteScreen(ModalScreen[bool]):
            """Modal screen to confirm host deletion."""

            BINDINGS = [("escape", "cancel_delete", "Cancel")]

            DEFAULT_CSS = """
            ConfirmDeleteScreen {
                align: center middle;
            }

            #delete-dialog {
                width: 50;
                height: auto;
                border: thick $error;
                background: $surface;
                padding: 1 2;
            }

            #delete-dialog Label {
                width: 100%;
                margin: 1 0;
            }

            #delete-dialog #btn-row {
                width: 100%;
                align: right middle;
                height: auto;
                margin: 1 0 0 0;
            }

            #delete-dialog Button {
                margin: 0 0 0 1;
            }
            """

            def __init__(self, host: Host):
                super().__init__()
                self.host = host

            def compose(self):
                with Container(id="delete-dialog"):
                    yield Label(
                        f"[bold]Delete host?[/bold]\n\n"
                        f"Name:   [bold]{self.host.name}[/bold]\n"
                        f"Target: [bold]{self.host.target}[/bold]"
                    )
                    with Container(id="btn-row"):
                        yield Button("Cancel", variant="default", id="cancel-btn")
                        yield Button("[bold]Delete[/bold]", variant="error", id="delete-btn")

            def action_cancel_delete(self):
                self.dismiss(False)

            def on_button_pressed(self, event: Button.Pressed):
                if event.button.id == "delete-btn":
                    self.dismiss(True)
                else:
                    self.dismiss(False)

        selected = {"target": None}
        hosts = self.hosts
        store_ref = store

        def rebuild_listview(app: App, hosts_list: List[Host]):
            """Replace the ListView with an updated host list."""
            lv = app.query_one(ListView)
            lv.clear()
            for i, host in enumerate(hosts_list):
                lv.append(ListItem(Label(f" [{i}]   {host.name}    {host.target}")))

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
                Binding("q", "quit", "Quit"),
                Binding("ctrl+c", "quit", "Quit", show=False),
                Binding("a", "add", "Add Host"),
                Binding("d", "delete", "Delete Host"),
                *[
                    Binding(str(d), f"select({d})", f"Select #{d}", show=False)
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

            def on_mount(self) -> None:
                if not hosts:
                    self.push_screen(AddHostScreen(), self._add_callback)

            def on_list_view_selected(self, event):
                idx = event.list_view.index
                selected["target"] = hosts[idx].target
                self.exit()

            def action_select(self, digit: int) -> None:
                """Select host by digit shortcut (0-9)."""
                if digit < len(hosts):
                    selected["target"] = hosts[digit].target
                    self.exit()

            def action_add(self) -> None:
                """Open modal to add a new host."""
                self.push_screen(AddHostScreen(), self._add_callback)

            def action_delete(self) -> None:
                """Delete the currently highlighted host."""
                lv = self.query_one(ListView)
                if lv.index is None or not hosts:
                    self.notify("No host selected.", severity="warning")
                    return
                idx = lv.index
                host_to_delete = hosts[idx]
                # Confirm deletion
                self.push_screen(
                    ConfirmDeleteScreen(host_to_delete),
                    lambda confirmed: self._delete_callback(idx, confirmed),
                )

            def _delete_callback(self, idx: int, confirmed: bool):
                if not confirmed:
                    return
                host_name = hosts[idx].name
                host_target = hosts[idx].target
                del hosts[idx]
                store_ref.save(list(hosts))
                self.notify(
                    f"Deleted [bold]{host_name}[/bold] ({host_target})",
                    title="Host deleted",
                )
                rebuild_listview(self, hosts)

            def _add_callback(self, data: str | None):
                if not data:
                    return
                try:
                    info = json.loads(data)
                except Exception:
                    return
                new_host = Host(name=info["name"], target=info["target"])
                store_ref.add(new_host)
                hosts.clear()
                hosts.extend(store_ref.load())
                self.notify(
                    f"Added [bold]{info['name']}[/bold] → {info['target']}",
                    title="Host saved",
                )
                rebuild_listview(self, hosts)

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
        target = Picker(hosts).run()

        if not target:
            sys.exit(0)

    maybe_save_host(target)

    friendly_name = ""
    host = store.find_by_target(target)
    if host:
        friendly_name = host.name

    ensure_ghostty_terminfo(target)
    ssh_into_host(target, friendly_name)


if __name__ == "__main__":
    main()

