import csv
import io
import time
from datetime import datetime
from pathlib import Path

from libgcs.file import File as GCSFile
from libgcs.serial_tools import ALL_BAUD, ALL_BAUD_STR, SerialPort, SerialReader, SerialThread
from rich.text import Text
from textual import on, events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll, HorizontalScroll, Vertical
from textual.message import Message
from textual.widgets import (
    TabbedContent, TabPane, Tab, Placeholder, Static, Log, RichLog,
    Input, Button, Switch, Select, Label,
)

from ..utils.colors import *
from ..utils import printable_bytes

_HISTORY_FILE = Path.home() / '.pyserialmon_history'
_HISTORY_MAX = 1000


class HistoryInput(Input):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_draft: str = ''
        self._load_history()

    def _load_history(self) -> None:
        if _HISTORY_FILE.exists():
            self._history = [l for l in _HISTORY_FILE.read_text().splitlines() if l]

    def _save_history(self) -> None:
        _HISTORY_FILE.write_text('\n'.join(self._history[-_HISTORY_MAX:]) + '\n')

    def add_to_history(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            self._save_history()
        self._history_index = -1
        self._current_draft = ''

    def on_key(self, event: events.Key) -> None:
        if event.key == 'up':
            if not self._history:
                return
            event.prevent_default()
            if self._history_index == -1:
                self._current_draft = self.value
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            self.cursor_position = len(self.value)
        elif event.key == 'down':
            if self._history_index == -1:
                return
            event.prevent_default()
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.value = self._history[self._history_index]
            else:
                self._history_index = -1
                self.value = self._current_draft
            self.cursor_position = len(self.value)


_CSV_COLORS = [
    'cyan', 'yellow', 'green', 'magenta',
    'bright_red', 'bright_blue', 'bright_cyan', 'bright_yellow',
    'bright_green', 'bright_magenta',
]


class DualMonitor(Static):
    def __init__(self, log_monitor, hex_monitor, sbs_log, sbs_hex):
        super().__init__()
        self.log_monitor = log_monitor
        self.hex_monitor = hex_monitor
        self.sbs_log = sbs_log
        self.sbs_hex = sbs_hex

    def compose(self) -> ComposeResult:
        with TabbedContent(id='tabbed-log'):
            with TabPane('ASCII View'):
                yield self.log_monitor
            with TabPane('Hex View'):
                yield self.hex_monitor
            with TabPane('Side-by-Side'):
                yield Container(HorizontalScroll(
                    self.sbs_log,
                    self.sbs_hex,
                ))


class SerialMonitorTab(Static):
    class CloseRequested(Message):
        def __init__(self, tab_index: int) -> None:
            super().__init__()
            self.tab_index = tab_index

    SM_OPTIONS = [
        ('No Line', (False, False)),
        ('LF Only', (False, True)),
        ('CR Only', (True, False)),
        ('Both CRLF', (True, True))
    ]

    def __init__(self, tab_index: int, /, max_lines: int | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._tab_index = tab_index
        self._serial_port = SerialPort()
        self._serial_reader = SerialReader(self._serial_port)
        self._serial_thread = SerialThread(self._serial_reader)
        self._serial_thread.start()

        self._port_con = False
        self._file: GCSFile | None = None
        self._baud_init = False
        self._show_timestamps = False
        self._line_buffer: str = ''
        self._bytes_received = 0
        self._last_tab_label: str = ''

        # TOP BAR
        self.btn_clear = Button('Clear', variant='default', id='btn-clear')
        self.btn_refresh = Button('Refresh', variant='default', id='btn-refresh')
        self.sel_port = Select([], prompt='Select a serial Port', id='sel-port')
        self.sel_baud = Select(
            list(zip(ALL_BAUD_STR, ALL_BAUD)),
            allow_blank=False,
            value=115200,
            id='sel-baud',
        )
        self.btn_connect = Button('Connect', variant='success', id='btn-connect')
        self.btn_close = Button('Close', variant='warning', id='btn-close')
        self.hgroup_serial = Horizontal(
            self.btn_clear,
            self.btn_refresh,
            self.sel_port,
            self.sel_baud,
            self.btn_connect,
            self.btn_close,
            id='hgroup-serial',
        )

        # LOG MONITOR
        self.log_monitor = RichLog(
            highlight=False, auto_scroll=True, max_lines=max_lines, id='log-monitor'
        )

        # HEX MONITOR
        self.hex_monitor = Log(
            highlight=False, auto_scroll=True, max_lines=max_lines, id='hex-monitor'
        )

        # SBS MONITOR
        self.sbs_log = RichLog(
            highlight=False, auto_scroll=True, max_lines=max_lines, id='sbs-log'
        )
        self.sbs_hex = Log(
            highlight=False, auto_scroll=True, max_lines=max_lines, id='sbs-hex'
        )

        # BOTTOM BAR
        self.input_user = HistoryInput(
            placeholder='Type here to send a message via Serial Port',
            valid_empty=True,
            id='input-user',
            disabled=True,
        )
        self.btn_send = Button('Send', variant='primary', id='btn-send', disabled=True)
        self.sel_crlf = Select(
            self.SM_OPTIONS, allow_blank=False, value=(False, True), id='sel-crlf'
        )
        self.sw_capture = Switch(id='sw-capture')
        self.hgroup_user = Horizontal(
            self.sw_capture,
            Label('Capture', id='label-capture'),
            Container(self.input_user, id='con-input-user'),
            self.sel_crlf,
            self.btn_send,
            id='hgroup-user',
        )

    # ── UI state helpers ──────────────────────────────────────────────────────

    def _set_connected_state(self) -> None:
        self._port_con = True
        self.input_user.disabled = False
        self.btn_send.disabled = False
        self.btn_connect.variant = 'error'
        self.btn_connect.label = 'Disconnect'

    def _set_disconnected_state(self) -> None:
        self._port_con = False
        self.input_user.disabled = True
        self.btn_send.disabled = True
        self.btn_connect.variant = 'success'
        self.btn_connect.label = 'Connect'

    def _is_active_tab(self) -> bool:
        try:
            return self.app.query_one(SerialTabs).active_monitor is self
        except Exception:
            return True

    def _update_tab_label(self, label: str) -> None:
        if label == self._last_tab_label:
            return
        self._last_tab_label = label
        try:
            self.app.query_one(f'Tab#pane-monitor-{self._tab_index}', Tab).label = label
        except Exception:
            pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        options = tuple(SerialPort.ports().items())
        if options:
            self.sel_port.set_options(options)
            self.sel_port.value = options[0][1]

        self.set_interval(0.050, self.update_content)
        self.set_interval(0.050, self.update_status)

    def on_unmount(self) -> None:
        self._serial_port.disconnect()
        try:
            self._serial_thread.stop()
        except Exception:
            pass

    # ── Top-bar handlers ──────────────────────────────────────────────────────

    @on(Button.Pressed, '#btn-refresh')
    def handle_refresh(self) -> None:
        self._serial_port.refresh()
        options = SerialPort.ports()
        current_value = self.sel_port.value
        self.sel_port.set_options(tuple(options.items()))
        if current_value in options.values():
            self.sel_port.value = current_value
        self.app.notify('Port list refreshed.')

    @on(Button.Pressed, '#btn-close')
    def handle_close(self) -> None:
        self.post_message(self.CloseRequested(self._tab_index))

    @on(Select.Changed, '#sel-baud')
    def handle_baud_changed(self) -> None:
        if not self._baud_init:
            self._baud_init = True
            return

        if self._port_con and self._serial_port.is_connected():
            port = self._serial_port.name
            baud = int(self.sel_baud.selection or 115200)
            self._serial_port.disconnect()
            success = port is not None and self._serial_port.connect(port, baud)
            if success:
                self.app.notify(f'Reconnected at {baud} baud.')
            else:
                self._set_disconnected_state()
                self.app.notify(f'Could not reconnect at {baud} baud.', severity='error')

    @on(Select.Changed, '#sel-port')
    def handle_port_changed(self) -> None:
        if self._port_con and self._serial_port.is_connected():
            port = str(self.sel_port.selection or '')
            baud = int(self.sel_baud.selection or 115200)
            self._serial_port.disconnect()
            success = bool(port) and self._serial_port.connect(port, baud)
            if success:
                self.app.notify(f'Switched to {port}.')
            else:
                self._set_disconnected_state()
                self.app.notify(f'Could not connect to {port}.', severity='error')

    @on(Button.Pressed, '#btn-connect')
    def handle_connect(self) -> None:
        if not self._port_con:
            if self._serial_port.is_connected():
                self._serial_port.disconnect()

            port = self.sel_port.selection
            baud = self.sel_baud.selection

            if port is None:
                self.app.notify('No serial port selected.', severity='warning')
                return

            success = self._serial_port.connect(str(port), int(baud or 115200))
            if success:
                self._set_connected_state()
                self.app.notify(f'Connected to {port} at {baud} baud.', severity='information')
            else:
                self.app.notify(f'Failed to connect to {port}.', severity='error')
        else:
            self._serial_port.disconnect()
            self._set_disconnected_state()
            self.app.notify('Disconnected.')

    # ── Bottom-bar handlers ───────────────────────────────────────────────────

    @on(Button.Pressed, '#btn-send')
    @on(Input.Submitted, '#input-user')
    def handle_send(self, _event: Button.Pressed | Input.Submitted) -> None:
        text = str(self.input_user.value)
        self.input_user.add_to_history(text)
        self.input_user.clear()

        cr, lf = self.sel_crlf.selection or (False, True)
        if cr:
            text += '\r'
        if lf:
            text += '\n'

        if self._serial_port.is_connected():
            try:
                self._serial_port.device.write(text.encode())
            except OSError as exc:
                self.app.notify(f'Send failed: {exc}', severity='error')

    @on(Switch.Changed, '#sw-capture')
    def handle_capture(self, event: Switch.Changed) -> None:
        if event.value:
            capture_file = GCSFile(f'captures/capture_{int(time.time())}.txt', unique=True)
            self._file = capture_file
            self.app.notify(f'Capturing to {capture_file.path}', severity='information')
        else:
            self._file = None
            self.app.notify('Capture stopped.')

    # ── Timestamp helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _format_timestamp() -> str:
        now = datetime.now()
        return f'[{now.strftime("%H:%M:%S")}.{now.microsecond // 1000:03d}] '

    # ── CSV helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _colorize_csv(line: str) -> Text | None:
        if ',' not in line:
            return None
        try:
            fields = next(csv.reader(io.StringIO(line)))
        except Exception:
            return None
        if len(fields) < 2:
            return None
        result = Text()
        for i, field in enumerate(fields):
            if i > 0:
                result.append(',')
            result.append(field, style=_CSV_COLORS[i % len(_CSV_COLORS)])
        return result

    def _write_ascii_line(self, line: str) -> None:
        csv_text = self._colorize_csv(line)
        if self._show_timestamps:
            ts = self._format_timestamp()
            if csv_text is not None:
                display = Text(ts)
                display.append_text(csv_text)
            else:
                display = Text(ts + line)
        else:
            display = csv_text if csv_text is not None else Text(line)
        self.log_monitor.write(display)
        self.sbs_log.write(display)

    # ── Periodic update callbacks ─────────────────────────────────────────────

    def update_content(self) -> None:
        if not self._serial_thread.size():
            return

        stream: bytes = self._serial_thread.get()
        self._bytes_received += len(stream)

        stream_str: str = printable_bytes(stream)
        hex_str: str = ' '.join(f'{b:02X}' for b in stream)

        if self._show_timestamps:
            hex_display = f'{self._format_timestamp()}{hex_str}'
        else:
            hex_display = hex_str
        self.hex_monitor.write_line(hex_display)
        self.sbs_hex.write_line(hex_display)

        self._line_buffer += stream_str
        while '\n' in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split('\n', 1)
            self._write_ascii_line(line.rstrip('\r'))

        if len(self._line_buffer) > 4096:
            self._write_ascii_line(self._line_buffer)
            self._line_buffer = ''

        if self._file is not None:
            self._file.append(stream_str)

    def update_status(self) -> None:
        if not self._is_active_tab():
            return

        label_status: Label = self.app.query_one('#label-status', Label)

        kb = self._bytes_received / 1024
        rx = f'{kb:.1f} KB' if kb >= 1 else f'{self._bytes_received} B'

        if self._serial_port.is_connected():
            self.input_user.disabled = False
            self.btn_send.disabled = False
            if not self._port_con:
                self._set_connected_state()
            label_status.styles.background = StatusColor.GREEN
            label_status.update(
                f'CONNECTED to {self._serial_port.name} @ {self._serial_port.baud} baud  |  RX {rx}'
            )
            self._update_tab_label(f'Device {self._tab_index} [{self._serial_port.name}]')
        elif self._serial_port.is_reconnecting():
            self.input_user.disabled = True
            self.btn_send.disabled = True
            label_status.styles.background = StatusColor.ORANGE
            label_status.update(
                f'RECONNECTING to {self._serial_port.name} @ {self._serial_port.baud} baud…'
            )
            self._update_tab_label(f'Device {self._tab_index} [reconnecting…]')
        else:
            self.input_user.disabled = True
            self.btn_send.disabled = True
            if self._port_con:
                self._set_disconnected_state()
            label_status.styles.background = StatusColor.RED
            label_status.update(f'DISCONNECTED  |  RX {rx}')
            self._update_tab_label(f'Device {self._tab_index}')

    # ── Action methods (called from app bindings) ─────────────────────────────

    def sm_show_timestamp(self) -> None:
        self._show_timestamps = not self._show_timestamps
        state = 'ON' if self._show_timestamps else 'OFF'
        self.app.notify(f'Timestamps {state}.')

    def sm_capture(self) -> None:
        self.sw_capture.toggle()

    @on(Button.Pressed, '#btn-clear')
    def sm_clear_output(self) -> None:
        self.log_monitor.clear()
        self.hex_monitor.clear()
        self.sbs_log.clear()
        self.sbs_hex.clear()
        self._bytes_received = 0
        self._line_buffer = ''

    def compose(self) -> ComposeResult:
        sbs = DualMonitor(
            log_monitor=self.log_monitor,
            hex_monitor=self.hex_monitor,
            sbs_log=self.sbs_log,
            sbs_hex=self.sbs_hex,
        )
        yield self.hgroup_serial
        yield Container(sbs, id='con-dual')
        yield self.hgroup_user


class SerialSettingsTab(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield Placeholder('Coming soon!')


class SerialTabs(Static):
    def __init__(self, max_lines: int | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._max_lines = max_lines
        self._tab_counter = 0

    def _make_monitor_tab(self) -> tuple[int, SerialMonitorTab]:
        self._tab_counter += 1
        n = self._tab_counter
        tab = SerialMonitorTab(
            n, max_lines=self._max_lines,
            id=f'tab-monitor-{n}', classes='tab-content',
        )
        return n, tab

    def _new_monitor_pane(self) -> TabPane:
        n, tab = self._make_monitor_tab()
        return TabPane(f'Device {n}', Container(tab), id=f'pane-monitor-{n}')

    def compose(self) -> ComposeResult:
        n, tab = self._make_monitor_tab()
        with TabbedContent(id='tabs-main'):
            with TabPane(f'Device {n}', id=f'pane-monitor-{n}'):
                yield Container(tab)
            with TabPane('+', id='pane-add'):
                pass
            with TabPane('Settings', id='pane-settings'):
                yield SerialSettingsTab(id='tab-settings', classes='tab-content')

    @property
    def active_monitor(self) -> SerialMonitorTab | None:
        try:
            active = self.query_one('#tabs-main', TabbedContent).active
            if not active or not active.startswith('pane-monitor-'):
                return None
            return self.query_one(f'#{active}').query_one(SerialMonitorTab)
        except Exception:
            return None

    async def add_device(self) -> None:
        tabs = self.query_one('#tabs-main', TabbedContent)
        pane = self._new_monitor_pane()
        await tabs.add_pane(pane, before='pane-add')
        tabs.active = f'pane-monitor-{self._tab_counter}'

    @on(TabbedContent.TabActivated, '#tabs-main')
    async def handle_add_tab_clicked(self, event: TabbedContent.TabActivated) -> None:
        if event.pane and event.pane.id == 'pane-add':
            await self.add_device()

    @on(SerialMonitorTab.CloseRequested)
    async def handle_close_tab(self, event: SerialMonitorTab.CloseRequested) -> None:
        tabs = self.query_one('#tabs-main', TabbedContent)
        pane_id = f'pane-monitor-{event.tab_index}'
        monitor_panes = [
            p for p in tabs.query(TabPane)
            if p.id and p.id.startswith('pane-monitor-')
        ]
        if len(monitor_panes) <= 1:
            self.app.notify('Cannot close the last device tab.', severity='warning')
            return
        other = next((p for p in monitor_panes if p.id != pane_id), None)
        if other:
            tabs.active = other.id
        await tabs.remove_pane(pane_id)