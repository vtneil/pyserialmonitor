from libgcs.preference_tools import PreferenceTree
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
        ("d", "toggle_dark", "Toggle dark mode")
    ]

    def __init__(self):
        super().__init__()
        self._pref = PreferenceTree.from_file(resolve('config', 'config.toml'), fmt='toml')
        self.title = self._pref['app']['title']
        self.sub_title = self._pref['app']['subtitle']

        self.counter = 1

        self.label_status = Label('DISCONNECTED', id='label-status')
        self.label_status.styles.background = StatusColor.RED
        self.tabs_serial = SerialTabs(id='tabs-serial')

    def on_mount(self) -> None:
        self.theme = self._pref['textual']['theme']
        self.set_interval(0.5, self.update_text)

    def update_text(self) -> None:
        self.label_status.update(f'COUNTER {self.counter}')
        self.label_status.styles.background = StatusColor.GREEN
        self.counter += 91

    def compose_body(self) -> ComposeResult:
        _ = self
        yield Container(
            self.tabs_serial,
            self.label_status,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self.compose_body()
        yield Footer()


if __name__ == '__main__':
    app = SerialApp()
    app.run()
