import csv
import io
import json
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

_CONFIG_FILE = Path.home() / '.pyserialmon_config'

_DEFAULT_PRESETS: dict[str, list[tuple[str, str]]] = {
    'AT Commands': [
        ('ATE0',       'ATE0'),
        ('ATI',        'ATI'),
        ('ATZ',        'ATZ'),
        ('AT+GMR',     'AT+GMR'),
        ('AT+CWMODE?', 'AT+CWMODE?'),
        ('AT+CWLAP',   'AT+CWLAP'),
        ('AT+RST',     'AT+RST'),
    ],
    'NMEA': [
        ('PUBX,00', '$PUBX,00*33'),
        ('PUBX,04', '$PUBX,04*37'),
        ('GGA',     '$GPGGA'),
        ('RMC',     '$GPRMC'),
    ],
}


def _load_macro_config() -> dict[str, list[tuple[str, str]]]:
    if _CONFIG_FILE.exists():
        try:
            raw = json.loads(_CONFIG_FILE.read_text())
            return {k: [(m[0], m[1]) for m in v] for k, v in raw.get('presets', {}).items()}
        except Exception:
            pass
    _save_macro_config(_DEFAULT_PRESETS)
    return dict(_DEFAULT_PRESETS)


def _save_macro_config(presets: dict[str, list[tuple[str, str]]]) -> None:
    data = {'presets': {k: [list(m) for m in v] for k, v in presets.items()}}
    _CONFIG_FILE.write_text(json.dumps(data, indent=2))


class MacroSend(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class MacroChanged(Message):
    pass


class MacroRow(Static):
    DEFAULT_CSS = """
    MacroRow {
        height: auto;
        layout: vertical;
    }
    MacroRow Horizontal {
        height: auto;
    }
    MacroRow .macro-edit { display: none; }
    MacroRow.editing .macro-normal { display: none; }
    MacroRow.editing .macro-edit { display: block; }
    MacroRow .btn-macro-send { width: 1fr; }
    MacroRow .btn-macro-edit { width: 5; min-width: 5; }
    MacroRow .btn-macro-delete { width: 5; min-width: 5; }
    MacroRow .btn-macro-save { width: auto; }
    MacroRow .btn-macro-cancel { width: auto; }
    MacroRow .input-macro-label { width: 1fr; }
    MacroRow .input-macro-text { width: 2fr; }
    """

    def __init__(self, label: str, text: str) -> None:
        super().__init__()
        self._label = label
        self._text = text

    def compose(self) -> ComposeResult:
        with Horizontal(classes='macro-normal'):
            yield Button(self._label, classes='btn-macro-send')
            yield Button('✎', classes='btn-macro-edit')
            yield Button('✕', variant='error', classes='btn-macro-delete')
        with Horizontal(classes='macro-edit'):
            yield Input(value=self._label, placeholder='Label', classes='input-macro-label')
            yield Input(value=self._text, placeholder='Text', classes='input-macro-text')
            yield Button('✓', variant='success', classes='btn-macro-save')
            yield Button('✕', classes='btn-macro-cancel')

    @on(Button.Pressed, '.btn-macro-send')
    def handle_send(self) -> None:
        self.post_message(MacroSend(self._text))

    @on(Button.Pressed, '.btn-macro-edit')
    def handle_edit(self) -> None:
        self.add_class('editing')

    @on(Button.Pressed, '.btn-macro-save')
    def handle_save(self) -> None:
        label = self.query_one('.input-macro-label', Input).value.strip()
        text = self.query_one('.input-macro-text', Input).value
        if label:
            self._label = label
            self._text = text
            self.query_one('.btn-macro-send', Button).label = label
        self.remove_class('editing')
        self.post_message(MacroChanged())

    @on(Button.Pressed, '.btn-macro-cancel')
    def handle_cancel(self) -> None:
        self.query_one('.input-macro-label', Input).value = self._label
        self.query_one('.input-macro-text', Input).value = self._text
        self.remove_class('editing')

    @on(Button.Pressed, '.btn-macro-delete')
    def handle_delete(self) -> None:
        self.remove()
        self.post_message(MacroChanged())


class MacrosPanel(Static):
    DEFAULT_CSS = """
    MacrosPanel {
        height: 1fr;
        width: 2fr;
        border-left: tall $panel;
        padding: 0 1;
        layout: vertical;
    }
    MacrosPanel #preset-bar { height: auto; }
    MacrosPanel #new-preset-bar { height: auto; display: none; }
    MacrosPanel.adding-preset #new-preset-bar { display: block; }
    MacrosPanel #macro-scroll { height: 1fr; width: 1fr; }
    MacrosPanel #hgroup-macro-add { height: auto; width: 1fr; }
    MacrosPanel #sel-macro-preset { width: 1fr; }
    MacrosPanel #btn-preset-add { width: auto; min-width: 3; }
    MacrosPanel #btn-preset-delete { width: auto; min-width: 3; }
    MacrosPanel #input-new-preset { width: 1fr; }
    MacrosPanel #btn-preset-create { width: auto; }
    MacrosPanel #btn-preset-create-cancel { width: auto; }
    MacrosPanel #input-macro-label { width: 1fr; }
    MacrosPanel #input-macro-text { width: 2fr; }
    MacrosPanel #btn-macro-add { width: auto; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._presets: dict[str, list[tuple[str, str]]] = _load_macro_config()
        self._active_preset: str | None = next(iter(self._presets), None)

    def compose(self) -> ComposeResult:
        with Horizontal(id='preset-bar'):
            yield Select(
                [(k, k) for k in self._presets],
                value=self._active_preset or Select.BLANK,
                allow_blank=True,
                prompt='Select preset…',
                id='sel-macro-preset',
            )
            yield Button('+', id='btn-preset-add')
            yield Button('✕', variant='error', id='btn-preset-delete')
        with Horizontal(id='new-preset-bar'):
            yield Input(placeholder='New preset name…', id='input-new-preset')
            yield Button('Create', variant='success', id='btn-preset-create')
            yield Button('Cancel', id='btn-preset-create-cancel')
        yield VerticalScroll(id='macro-scroll')
        with Horizontal(id='hgroup-macro-add'):
            yield Input(placeholder='Label', id='input-macro-label')
            yield Input(placeholder='Text to send', id='input-macro-text')
            yield Button('Add', variant='success', id='btn-macro-add')

    async def on_mount(self) -> None:
        if self._active_preset:
            await self._load_preset(self._active_preset)

    # ── Preset helpers ────────────────────────────────────────────────────────

    async def _load_preset(self, name: str) -> None:
        self._active_preset = name
        scroll = self.query_one('#macro-scroll', VerticalScroll)
        await scroll.remove_children()
        for label, text in self._presets.get(name, []):
            await scroll.mount(MacroRow(label, text))

    def _sync_and_save(self) -> None:
        if self._active_preset is None:
            return
        scroll = self.query_one('#macro-scroll', VerticalScroll)
        self._presets[self._active_preset] = [
            (row._label, row._text) for row in scroll.query(MacroRow)
        ]
        _save_macro_config(self._presets)

    def _update_select(self) -> None:
        sel = self.query_one('#sel-macro-preset', Select)
        sel.set_options([(k, k) for k in self._presets])
        if self._active_preset in self._presets:
            sel.value = self._active_preset
        elif self._presets:
            self._active_preset = next(iter(self._presets))
            sel.value = self._active_preset
        else:
            self._active_preset = None

    async def _create_preset(self) -> None:
        name = self.query_one('#input-new-preset', Input).value.strip()
        if not name:
            return
        if name in self._presets:
            self.app.notify(f'Preset "{name}" already exists.', severity='warning')
            return
        self._presets[name] = []
        _save_macro_config(self._presets)
        self._update_select()
        await self._load_preset(name)
        self.query_one('#input-new-preset', Input).clear()
        self.remove_class('adding-preset')

    # ── Preset bar handlers ───────────────────────────────────────────────────

    @on(Select.Changed, '#sel-macro-preset')
    async def handle_preset_selected(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK or str(event.value) == self._active_preset:
            return
        await self._load_preset(str(event.value))

    @on(Button.Pressed, '#btn-preset-add')
    def handle_preset_add(self) -> None:
        self.add_class('adding-preset')
        self.query_one('#input-new-preset', Input).focus()

    @on(Button.Pressed, '#btn-preset-create')
    async def handle_preset_create(self) -> None:
        await self._create_preset()

    @on(Input.Submitted, '#input-new-preset')
    async def handle_new_preset_submitted(self) -> None:
        await self._create_preset()

    @on(Button.Pressed, '#btn-preset-create-cancel')
    def handle_preset_create_cancel(self) -> None:
        self.query_one('#input-new-preset', Input).clear()
        self.remove_class('adding-preset')

    @on(Button.Pressed, '#btn-preset-delete')
    async def handle_preset_delete(self) -> None:
        if self._active_preset is None:
            return
        del self._presets[self._active_preset]
        _save_macro_config(self._presets)
        prev = self._active_preset
        self._update_select()
        scroll = self.query_one('#macro-scroll', VerticalScroll)
        if self._active_preset and self._active_preset != prev:
            await self._load_preset(self._active_preset)
        else:
            await scroll.remove_children()

    # ── Macro list handlers ───────────────────────────────────────────────────

    @on(Button.Pressed, '#btn-macro-add')
    async def handle_macro_add(self) -> None:
        label = self.query_one('#input-macro-label', Input).value.strip()
        text = self.query_one('#input-macro-text', Input).value
        if not label or not text or self._active_preset is None:
            return
        await self.query_one('#macro-scroll', VerticalScroll).mount(MacroRow(label, text))
        self.query_one('#input-macro-label', Input).clear()
        self.query_one('#input-macro-text', Input).clear()
        self._sync_and_save()

    @on(MacroChanged)
    def handle_macro_changed(self) -> None:
        self._sync_and_save()


class DualMonitor(Static):
    def __init__(self, log_monitor, hex_monitor, sbs_log, sbs_hex, macros_log, macros_panel):
        super().__init__()
        self.log_monitor = log_monitor
        self.hex_monitor = hex_monitor
        self.sbs_log = sbs_log
        self.sbs_hex = sbs_hex
        self.macros_log = macros_log
        self.macros_panel = macros_panel

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
            with TabPane('Macros'):
                with Horizontal(id='hgroup-macros'):
                    yield self.macros_log
                    yield self.macros_panel


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
        self._paused = False
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
        self.btn_pause = Button('Pause', variant='warning', id='btn-pause')
        self.btn_close = Button('Close', variant='error', id='btn-close')
        self.hgroup_serial = Horizontal(
            self.btn_clear,
            self.btn_refresh,
            self.sel_port,
            self.sel_baud,
            self.btn_connect,
            self.btn_pause,
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

        # MACROS MONITOR
        self.macros_log = RichLog(
            highlight=False, auto_scroll=True, max_lines=max_lines, id='macros-log'
        )
        self.macros_panel = MacrosPanel(id='macros-panel')

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

    @on(Button.Pressed, '#btn-pause')
    def handle_pause(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.label = 'Resume'
            self.btn_pause.variant = 'success'
        else:
            self.btn_pause.label = 'Pause'
            self.btn_pause.variant = 'warning'

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
        self.macros_log.write(display)

    # ── Periodic update callbacks ─────────────────────────────────────────────

    def update_content(self) -> None:
        if self._paused or not self._serial_thread.size():
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
        self.macros_log.clear()
        self._bytes_received = 0
        self._line_buffer = ''

    @on(MacroSend)
    def handle_macro_send(self, event: MacroSend) -> None:
        text = event.text
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

    def compose(self) -> ComposeResult:
        sbs = DualMonitor(
            log_monitor=self.log_monitor,
            hex_monitor=self.hex_monitor,
            sbs_log=self.sbs_log,
            sbs_hex=self.sbs_hex,
            macros_log=self.macros_log,
            macros_panel=self.macros_panel,
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