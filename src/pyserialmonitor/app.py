from libgcs.preference_tools import PreferenceTree
from libgcs.serial_tools import SerialPort, SerialReader
from pyserialmonitor.widgets.serial_tabs import SerialMonitorTab
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Label

from .utils import *
from .utils.colors import *
from .widgets.serial_tabs import SerialTabs


class SerialApp(App):
    CSS_PATH = [
        resolve('styles', 'main.tcss'),
    ]

    BINDINGS = [
        # ('f1', 'sm_show_timestamp', 'Show Timestamp'),
        ('f2', 'sm_capture', 'Start/Stop Capturing'),
        ('f3', 'sm_clear_output', 'Clear Output'),
        ('d', 'toggle_dark', 'Toggle Light/Dark')
    ]

    def __init__(self):
        super().__init__()

        ### Initialize the backends
        self._pref = PreferenceTree.from_file(resolve('config', 'config.toml'), fmt='toml')
        self._port = SerialPort()
        self._reader = SerialReader(self._port)
        self.counter = 1

        ### Initialize the frontends
        self.title = self._pref['app']['title']
        self.sub_title = self._pref['app']['subtitle']

        self.label_status = Label('DISCONNECTED', id='label-status')
        self.label_status.styles.background = StatusColor.RED
        self.tabs_serial = SerialTabs(self._port, self._reader, id='tabs-serial')

    def on_mount(self) -> None:
        self.theme = self._pref['textual']['theme']

    def compose_body(self) -> ComposeResult:
        _ = self
        yield Container(
            self.tabs_serial,
            self.label_status,
        )

    def action_sm_show_timestamp(self) -> None:
        self.query_one(SerialMonitorTab).sm_show_timestamp()

    def action_sm_capture(self) -> None:
        self.query_one(SerialMonitorTab).sm_capture()

    def action_sm_clear_output(self) -> None:
        self.query_one(SerialMonitorTab).sm_clear_output()

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self.compose_body()
        yield Footer()


if __name__ == '__main__':
    app = SerialApp()
    app.run()
