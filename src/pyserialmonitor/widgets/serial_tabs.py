import time

from libgcs.file import File
from libgcs.serial_tools import ALL_BAUD, ALL_BAUD_STR, SerialPort, SerialReader, SerialThread
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import TabbedContent, TabPane, Placeholder, Static, Log, Input, Button, Switch, Select, Label

from ..utils.colors import *


class SerialMonitorTab(Static):
    SM_OPTIONS = [
        ('No Line', (False, False)),
        ('LF Only', (False, True)),
        ('CR Only', (True, False)),
        ('Both CRLF', (True, True))
    ]

    def __init__(self, port: SerialPort, reader: SerialReader, thread: SerialThread, /, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._serial_port = port
        self._serial_reader = reader
        self._serial_thread = thread
        self._port_con = False
        self._file: File | None = None

        # TOP BAR
        self.btn_clear = Button(
            'Clear',
            variant='default',
            id='btn-clear'
        )
        self.btn_refresh = Button(
            'Refresh',
            variant='default',
            id='btn-refresh'
        )
        self.sel_port = Select(
            [],
            prompt='Select a serial Port',
            id='sel-port'
        )
        self.sel_baud = Select(
            list(zip(ALL_BAUD_STR, ALL_BAUD)),
            allow_blank=False,
            value=115200,
            id='sel-baud'
        )
        self.btn_connect = Button(
            'Connect',
            variant='success',
            id='btn-connect'
        )
        self.hgroup_serial = Horizontal(
            self.btn_clear,
            self.btn_refresh,
            self.sel_port,
            self.sel_baud,
            self.btn_connect,
            id='hgroup-serial'
        )

        # LOG MONITOR
        self.log_monitor = Log(
            highlight=False,
            auto_scroll=True,
            id='log-monitor'
        )

        # HEX MONITOR
        self.hex_monitor = Log(
            highlight=False,
            auto_scroll=True,
            id='hex-monitor'
        )

        # BOTTOM BAR
        self.input_user = Input(
            placeholder='Type here to send a message via Serial Port',
            valid_empty=True,
            id='input-user',
            disabled=True
        )
        self.btn_send = Button(
            'Send',
            variant='primary',
            id='btn-send',
            disabled=True
        )
        self.sel_crlf = Select(
            self.SM_OPTIONS,
            allow_blank=False,
            value=(False, True),
            id='sel-crlf'
        )
        self.sw_capture = Switch(id='sw-capture')
        self.hgroup_user = Horizontal(
            self.sw_capture,
            Container(self.input_user),
            self.sel_crlf,
            self.btn_send,
            id='hgroup-user'
        )

    def on_mount(self) -> None:
        options = tuple(SerialPort.ports().items())
        if options:
            self.sel_port.set_options(options)
            self.sel_port.value = options[0][1]

        self.set_interval(0.050, self.update_content)
        self.set_interval(0.050, self.update_status)

    @on(Button.Pressed, '#btn-refresh')
    def handle_refresh(self) -> None:
        self._serial_port.refresh()
        options = SerialPort.ports()
        current_value = self.sel_port.value
        self.sel_port.set_options(tuple(options.items()))
        if current_value in options.values():
            self.sel_port.value = current_value

    @on(Button.Pressed, '#btn-connect')
    def handle_connect(self) -> None:
        def btn_connect():
            self._port_con = False
            self.input_user.disabled = True
            self.btn_send.disabled = True
            self.btn_connect.variant = 'success'
            self.btn_connect.label = 'Connect'

        def btn_disconnect():
            self._port_con = True
            self.input_user.disabled = False
            self.btn_send.disabled = False
            self.btn_connect.variant = 'error'
            self.btn_connect.label = 'Disconnect'

        if not self._port_con:
            if not self._serial_port.is_connected():
                port = self.sel_port.selection
                baud = self.sel_baud.selection
                success = port is not None and self._serial_port.connect(port, baud)
                if port and success:
                    btn_disconnect()
                else:
                    self._serial_port.disconnect()
                    btn_connect()
            else:
                self._serial_port.disconnect()
                btn_connect()
        else:
            if self._serial_port.is_connected():
                self._serial_port.disconnect()
                btn_connect()
            else:
                self._serial_port.disconnect()
                btn_connect()

    @on(Button.Pressed, '#btn-send')
    @on(Input.Submitted, '#input-user')
    def handle_send(self, event: Button.Pressed | Input.Submitted) -> None:
        text = str(self.input_user.value)
        self.input_user.clear()

        if self.sel_crlf.selection[0]:
            text += '\r'
        if self.sel_crlf.selection[1]:
            text += '\n'

        if self._serial_port.is_connected():
            self._serial_port.device.write(text.encode())

    @on(Switch.Changed, '#sw-capture')
    def handle_capture(self, event: Switch.Changed) -> None:
        if event.value:
            # START RECORD
            self._file = File(f'captures/capture_{int(time.time())}.txt', unique=True)
        else:
            # STOP RECORD
            self._file = None

    def update_content(self) -> None:
        if self._serial_thread.size():
            stream: bytes = self._serial_thread.get()
            stream_str: str = stream.decode()
            self.log_monitor.write(stream_str)  # Log to monitor
            self.hex_monitor.write_line(' '.join(f'{b:02X}' for b in stream))  # Log to hex monitor
            if self._file is not None:  # Log to file
                self._file.append(stream_str)

    def update_status(self) -> None:
        label_status: Label = self.app.query_one('#label-status')

        if self._serial_port.is_connected():
            self.input_user.disabled = False
            self.btn_send.disabled = False
            label_status.styles.background = StatusColor.GREEN
            label_status.update(f'CONNECTED to {self._serial_port.name} with baud {self._serial_port.baud}')
        elif self._serial_port.is_reconnecting():
            self.input_user.disabled = True
            self.btn_send.disabled = True
            label_status.styles.background = StatusColor.ORANGE
            label_status.update(f'RECONNECTING to {self._serial_port.name} with baud {self._serial_port.baud}...')
        else:
            self.input_user.disabled = True
            self.btn_send.disabled = True
            label_status.styles.background = StatusColor.RED
            label_status.update('DISCONNECTED')

    def sm_show_timestamp(self) -> None:
        pass

    def sm_capture(self) -> None:
        self.sw_capture.toggle()

    @on(Button.Pressed, '#btn-clear')
    def sm_clear_output(self) -> None:
        self.log_monitor.clear()
        self.hex_monitor.clear()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.hgroup_serial
            with TabbedContent():
                with TabPane('ASCII View'):
                    yield self.log_monitor
                with TabPane('Hex View'):
                    yield self.hex_monitor
            yield self.hgroup_user


class SerialSettingsTab(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield Placeholder('Coming soon!')


class SerialTabs(Static):
    def __init__(self, port: SerialPort, reader: SerialReader, thread: SerialThread, /, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tab_monitor = SerialMonitorTab(port, reader, thread, id='tab-monitor', classes='tab-content')
        self.tab_settings = SerialSettingsTab(id='tab-settings', classes='tab-content')

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane('Monitor'):
                yield Container(self.tab_monitor)

            with TabPane('Settings'):
                yield Container(self.tab_settings)
