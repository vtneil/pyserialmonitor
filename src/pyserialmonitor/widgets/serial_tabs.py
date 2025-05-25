from libgcs.serial import ALL_BAUD, ALL_BAUD_STR
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, HorizontalGroup
from textual.widgets import TabbedContent, TabPane, Placeholder, Static, Label, Log, Input, Button, Switch, Select

from ..utils.colors import *


class SerialMonitorTab(Static):
    SM_OPTIONS = [
        ('No Line', (False, False)),
        ('LF Only', (False, True)),
        ('CR Only', (True, False)),
        ('Both CRLF', (True, True))
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # TOP BAR
        self.sel_port = Select(
            [],
            prompt='Select a serial Port',
            id='sel-port'
        )
        self.sel_baud = Select(
            list(zip(ALL_BAUD_STR, ALL_BAUD)),
            allow_blank=False,
            id='sel-baud'
        )
        self.btn_serial = Button(
            'Connect',
            variant='success',
            id='btn-serial'
        )
        self.hgroup_serial = Horizontal(
            self.sel_port,
            self.sel_baud,
            self.btn_serial,
            id='hgroup-serial'
        )

        # LOG MONITOR
        self.log_monitor = Log(
            highlight=False,
            auto_scroll=True,
            id='log-monitor'
        )

        # BOTTOM BAR
        self.input_user = Input(
            placeholder='Type here to send a message via Serial Port',
            valid_empty=True,
            id='input-user'
        )
        self.btn_send = Button(
            'Send',
            variant='primary',
            id='btn-send'
        )
        self.sel_crlf = Select(
            self.SM_OPTIONS,
            allow_blank=False,
            value=(False, True),
            id='sel-crlf'
        )
        self.switch_time = Switch(id='switch-time')
        self.hgroup_user = Horizontal(
            self.switch_time,
            Container(self.input_user),
            self.sel_crlf,
            self.btn_send,
            id='hgroup-user'
        )

        self.counter = 40

    def on_mount(self) -> None:
        for i in range(40):
            self.log_monitor.write_line(f'hello world {i}')
        self.set_interval(0.1, self.update_content)

    @on(Button.Pressed, '#btn-send')
    def handle_send(self):
        self.styles.background = StatusColor.RED

    @on(Input.Submitted, '#input-user')
    def handle_input_send(self):
        self.handle_send()

    def update_content(self) -> None:
        self.log_monitor.write_line(f'hello world {self.counter}')
        self.counter += 1

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.hgroup_serial
            yield self.log_monitor
            yield self.hgroup_user


class SerialSettingsTab(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield Placeholder()


class SerialTabs(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tab_monitor = SerialMonitorTab(id='tab-monitor', classes='tab-content')
        self.tab_settings = SerialSettingsTab(id='tab-settings', classes='tab-content')

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane('Monitor',
                         id='pane-monitor'):
                yield Container(self.tab_monitor)

            with TabPane('Settings',
                         id='pane-settings'):
                yield Container(self.tab_settings)
