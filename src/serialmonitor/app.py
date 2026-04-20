from libgcs.preference_tools import PreferenceTree
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Label

from .utils import *
from .utils.colors import *
from .widgets.serial_tabs import SerialMonitorTab, SerialTabs


class SerialApp(App):
    CSS_PATH = [
        resolve('styles', 'main.tcss'),
    ]

    BINDINGS = [
        ('f1', 'sm_show_timestamp', 'Timestamps On/Off'),
        ('f2', 'sm_capture', 'Start/Stop Capturing'),
        ('f3', 'sm_clear_output', 'Clear Output'),
        ('f4', 'sm_connect', 'Connect/Disconnect'),
        ('f5', 'sm_refresh', 'Refresh Port List'),
        ('f6', 'sm_add_device', 'Add Device'),
        ('d', 'toggle_dark', 'Toggle Light/Dark'),
    ]

    def __init__(self):
        super().__init__()

        self._pref = PreferenceTree.from_file(resolve('config', 'config.toml'), fmt='toml')

        self.title = self._pref['app']['title']
        self.sub_title = self._pref['app']['subtitle']

        max_lines = self._pref['monitor'].get('max_lines', 5000)

        self.label_status = Label('DISCONNECTED', id='label-status')
        self.label_status.styles.background = StatusColor.RED
        self.tabs_serial = SerialTabs(max_lines=max_lines, id='tabs-serial')

    def on_mount(self) -> None:
        self.theme = self._pref['textual']['theme']

    def compose_body(self) -> ComposeResult:
        _ = self
        yield Container(
            self.tabs_serial,
            self.label_status,
        )

    def _active_monitor(self) -> SerialMonitorTab | None:
        return self.query_one(SerialTabs).active_monitor

    def action_sm_show_timestamp(self) -> None:
        if tab := self._active_monitor():
            tab.sm_show_timestamp()

    def action_sm_capture(self) -> None:
        if tab := self._active_monitor():
            tab.sm_capture()

    def action_sm_clear_output(self) -> None:
        if tab := self._active_monitor():
            tab.sm_clear_output()

    def action_sm_connect(self) -> None:
        if tab := self._active_monitor():
            tab.handle_connect()

    def action_sm_refresh(self) -> None:
        if tab := self._active_monitor():
            tab.handle_refresh()

    async def action_sm_add_device(self) -> None:
        await self.query_one(SerialTabs).add_device()

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self.compose_body()
        yield Footer()


if __name__ == '__main__':
    app = SerialApp()
    app.run()