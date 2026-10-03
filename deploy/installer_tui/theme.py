"""Slate Ops design tokens: every colour, glyph and badge of the full-screen installer.

Colours are defined once here and reach the stylesheet as $variables. The palette is a
dark slate/blue-grey base with restrained tonal layers; cyan marks focus and the primary
action; green, amber and red mark outcomes and always travel with a status word.
256-colour and 16-colour terminals get Rich's nearest-colour mapping; NO_COLOR gets
monochrome output with reverse-video selection and bracketed status words; a non-UTF-8
terminal gets ASCII borders and glyphs.
"""
from rich.style import Style
from rich.text import Text

TOKENS = {
    'slate-bg': '#0F172A',          # screen background and gutters
    'slate-wash': '#17283B',        # header/footer bands
    'slate-panel': '#1E293B',       # panels
    'slate-elevated': '#27364C',    # dialogs, hover, inactive buttons
    'slate-border': '#3B4A61',      # unfocused panel borders
    'slate-text': '#F8FAFC',        # main text
    'slate-muted': '#CBD5E1',       # secondary text
    'slate-dim': '#94A3B8',         # tertiary text, hints
    'slate-accent': '#22D3EE',      # focus, primary action
    'slate-accent-soft': '#0E7490',  # selection indicator when its pane is not focused
    'slate-select': '#164E63',      # selected row fill (focused pane)
    'slate-select-blur': '#173A4D',  # selected row fill (pane not focused)
    'slate-success': '#4ADE80',
    'slate-warning': '#FBBF24',
    'slate-error': '#F87171',
    'slate-disabled': '#64748B',
}

T = TOKENS

# Without truecolor, Rich maps each colour to its nearest palette entry, which turns the slate
# greys into black and pure navy and makes both selection fills identical. These are exact
# xterm-256 entries chosen to keep the same layering (and distinct focused/unfocused selection).
TOKENS_256 = {
    'slate-bg': '#1C1C1C', 'slate-wash': '#262626', 'slate-panel': '#303030', 'slate-elevated': '#3A3A3A',
    'slate-border': '#585858', 'slate-text': '#EEEEEE', 'slate-muted': '#D0D0D0', 'slate-dim': '#A8A8A8',
    'slate-accent': '#00D7FF', 'slate-accent-soft': '#0087AF', 'slate-select': '#005F87',
    'slate-select-blur': '#005F5F', 'slate-success': '#5FD75F', 'slate-warning': '#FFD700',
    'slate-error': '#FF5F5F', 'slate-disabled': '#6C6C6C',
}


def color_system(environ):
    """'truecolor' or 'palette', decided the way Rich decides (COLORTERM first)."""
    if environ.get('TEXTUAL_COLOR_SYSTEM') == 'truecolor':
        return 'truecolor'
    if environ.get('TEXTUAL_COLOR_SYSTEM') in ('256', 'standard'):
        return 'palette'
    return 'truecolor' if environ.get('COLORTERM', '').lower() in ('truecolor', '24bit') else 'palette'


def apply_palette(system):
    """Switch the shared token table in place (before the app starts)."""
    if system == 'palette':
        TOKENS.update(TOKENS_256)

# State word -> (badge text, colour token). Every coloured state carries its word.
BADGES = {
    'Ready': ('READY', 'slate-success'),
    'Completed': ('COMPLETED', 'slate-success'),
    'Running': ('RUNNING', 'slate-accent'),
    'Checking': ('CHECKING', 'slate-accent'),
    'Waiting for input': ('WAITING', 'slate-warning'),
    'Needs authentication': ('NEEDS AUTH', 'slate-warning'),
    'Attention': ('ATTENTION', 'slate-warning'),
    'Partial': ('PARTIAL', 'slate-warning'),
    'Stopped': ('STOPPED', 'slate-warning'),
    'Failed': ('FAILED', 'slate-error'),
    'Unavailable': ('UNAVAILABLE', 'slate-dim'),
    'Not installed': ('NOT INSTALLED', 'slate-dim'),
    'Not set up': ('NOT SET UP', 'slate-dim'),
    'Not checked': ('NOT CHECKED', 'slate-dim'),
    'Pending': ('PENDING', 'slate-dim'),
    'Skipped': ('SKIPPED', 'slate-dim'),
    'Not started': ('NOT STARTED', 'slate-dim'),
    'Not selected': ('NOT SELECTED', 'slate-dim'),
    'PASS': ('PASS', 'slate-success'),
    'WARN': ('WARN', 'slate-warning'),
    'FAIL': ('FAIL', 'slate-error'),
    'SKIP': ('SKIP', 'slate-dim'),
    'INFO': ('INFO', 'slate-accent'),
}

GLYPHS = {
    'unicode': {'Completed': '✓', 'Running': '▸', 'Waiting for input': '?', 'Pending': '·', 'Failed': '✗',
                'Skipped': '–', 'Stopped': '■', 'Not started': '·', 'select': '▌', 'bullet': '•',
                'spinner': '-\\|/', 'sep': '│', 'ellipsis': '…'},
    'ascii': {'Completed': 'x', 'Running': '>', 'Waiting for input': '?', 'Pending': '.', 'Failed': '!',
              'Skipped': '-', 'Stopped': '#', 'Not started': '.', 'select': '>', 'bullet': '*',
              'spinner': '-\\|/', 'sep': '|', 'ellipsis': '...'},
}


class Look:
    """Rendering decisions for one terminal (colour and character capabilities)."""

    def __init__(self, no_color=False, ascii_only=False):
        self.no_color = no_color
        self.ascii = ascii_only
        self.glyphs = GLYPHS['ascii' if ascii_only else 'unicode']

    def badge(self, state, width=None):
        """A compact status chip: the word on its colour, or [WORD] in monochrome. `width`
        pads with plain space after the chip so columns align without a heavy bar."""
        word, token = BADGES.get(state, (str(state).upper(), 'slate-dim'))
        chip = Text()
        if self.no_color:
            chip.append(f'[{word}]', style='bold')
        else:
            chip.append(f' {word} ', style=Style(color=T['slate-bg'], bgcolor=T[token], bold=True))
        if width and chip.cell_len < width:
            chip.append(' ' * (width - chip.cell_len))
        return chip

    def state_color(self, state):
        return T[BADGES.get(state, ('', 'slate-dim'))[1]]

    def glyph(self, name):
        return self.glyphs.get(name, '·')

    def text(self, value, token='slate-text', bold=False):
        return Text(str(value), style=Style(color=None if self.no_color else T[token], bold=bold))


def css_variables():
    return dict(TOKENS)


STYLESHEET = r"""
Screen {
    background: $slate-bg;
    color: $slate-text;
    layers: base overlay;
}

/* ---- header and footer bands ---- */
#header {
    dock: top;
    height: 2;
    background: $slate-wash;
    padding: 0 2;
}
#header-title { height: 1; width: 1fr; }
#header-meta { height: 1; width: 1fr; color: $slate-muted; }
#footer {
    dock: bottom;
    height: 1;
    background: $slate-wash;
    color: $slate-muted;
    padding: 0 2;
}

/* ---- body and panels ---- */
.body { height: 1fr; padding: 1 2 0 2; background: $slate-bg; }
.panel {
    background: $slate-panel;
    border: round $slate-border;
    border-title-color: $slate-dim;
    border-title-style: bold;
    border-subtitle-color: $slate-dim;
    padding: 0 1;
}
.panel:focus-within, .panel:focus {
    border: round $slate-accent;
    border-title-color: $slate-accent;
    border-title-background: $slate-panel;
}
.panel.-attention { border: round $slate-warning; border-title-color: $slate-warning; }
.panel.-error { border: round $slate-error; border-title-color: $slate-error; }
.gap { width: 1; background: $slate-bg; }
.vgap { height: 1; background: $slate-bg; }

/* ---- action menu: full-width selected row, bold text, left indicator ---- */
#nav { background: $slate-panel; height: auto; max-height: 100%; }
#nav > ListItem {
    background: $slate-panel;
    color: $slate-muted;
    padding: 0 1 0 0;
    border-left: blank;
    height: 1;
}
#nav > ListItem.-hovered { background: $slate-elevated; color: $slate-text; }
#nav > ListItem.-highlight {
    background: $slate-select-blur;
    color: $slate-text;
    text-style: bold;
    border-left: outer $slate-accent-soft;
}
#nav:focus > ListItem.-highlight {
    background: $slate-select;
    color: $slate-text;
    text-style: bold;
    border-left: outer $slate-accent;
}
#nav > ListItem.-separator { color: $slate-dim; }
#nav-hint { color: $slate-dim; height: auto; padding: 0 0 0 1; dock: bottom; }

/* ---- details pane ---- */
#left-column { width: 36; }
#nav-panel { width: 100%; height: auto; }
#session-panel { height: 1fr; min-height: 5; }
#session { height: auto; }
#right-column { width: 1fr; }
#detail-panel { height: 1fr; min-height: 6; }
#status-panel { height: auto; }
.panel { scrollbar-color: $slate-border; scrollbar-color-hover: $slate-accent; scrollbar-color-active: $slate-accent;
         scrollbar-background: $slate-panel; scrollbar-background-hover: $slate-panel;
         scrollbar-background-active: $slate-panel; scrollbar-size-vertical: 1; }
#detail { background: $slate-panel; scrollbar-color: $slate-border; scrollbar-color-hover: $slate-accent;
          scrollbar-background: $slate-panel; scrollbar-size-vertical: 1; }
.section-title { color: $slate-accent; text-style: bold; height: 1; margin: 1 0 0 0; }
.section-title.-first { margin: 0; }
.prose { color: $slate-muted; height: auto; }
.statusline { height: auto; }

/* ---- buttons: compact, crisp, distinct focus/disabled ---- */
Button {
    height: 1;
    min-width: 10;
    border: none;
    padding: 0 2;
    margin: 0 1 0 0;
    background: $slate-elevated;
    color: $slate-text;
    text-style: none;
}
Button:hover { background: $slate-border; }
Button.primary { background: $slate-accent; color: $slate-bg; text-style: bold; }
Button.warning { background: $slate-warning; color: $slate-bg; text-style: bold; }
#recovery Button { background: $slate-border; }
#recovery Button.primary { background: $slate-accent; color: $slate-bg; }
/* One focus treatment for every kind, defined last: a near-white fill with an underlined label is
   used for nothing else, so the focused button is never ambiguous next to a cyan or amber one. */
Button:focus, Button.primary:focus, Button.warning:focus, #recovery Button:focus {
    background: $slate-text; color: $slate-bg; text-style: bold underline;
}
Button:disabled { background: $slate-panel; color: $slate-disabled; text-style: none; }
.buttons { height: 1; margin: 1 0 0 0; }
.buttons.bar { margin: 0; padding: 0 1; height: 2; padding-top: 1; background: $slate-bg; }

/* ---- forms ---- */
RadioSet { background: $slate-panel; border: none; padding: 0; height: auto; width: 1fr; }
RadioSet:focus { background: $slate-panel; }
RadioButton { background: $slate-panel; color: $slate-muted; padding: 0 1; }
RadioButton.-selected { color: $slate-text; text-style: bold; }
RadioSet:focus > RadioButton.-selected { background: $slate-select; }
RadioSet:focus-within > RadioButton.-selected { background: $slate-select; }
RadioButton:disabled { color: $slate-disabled; }
Checkbox { background: $slate-panel; border: none; padding: 0 1; color: $slate-muted; }
Checkbox:focus { background: $slate-select; color: $slate-text; text-style: bold; }
Input { background: $slate-elevated; border: tall $slate-border; color: $slate-text; height: 3; }
Input:focus { border: tall $slate-accent; }
Input.-invalid { border: tall $slate-error; }
.field-label { color: $slate-text; text-style: bold; height: 1; margin: 1 0 0 0; }
.field-help { color: $slate-dim; height: auto; }
.field-error { color: $slate-error; height: auto; }

/* ---- execution ---- */
#phase-panel { width: 52; }
#phases { background: $slate-panel; height: auto; max-height: 100%; }
#phases > ListItem { background: $slate-panel; height: 1; border-left: blank; }
#phases Label, #nav Label { width: 1fr; }
#phases > ListItem.-highlight { background: $slate-select-blur; border-left: outer $slate-accent-soft; }
#phases:focus > ListItem.-highlight { background: $slate-select; border-left: outer $slate-accent; }
#run-summary { color: $slate-dim; height: auto; padding: 1 0 0 1; }
#activity-panel { height: auto; min-height: 5; max-height: 70%; }
#activity { height: auto; }
#output-panel { height: 1fr; }
Log#output { background: #0B1220; color: $slate-muted; scrollbar-color: $slate-border;
          scrollbar-color-hover: $slate-accent; scrollbar-background: #0B1220; scrollbar-size-vertical: 1; }
Log#output:focus { background: #0B1220; }
#recovery { height: auto; display: none; background: $slate-elevated; border: round $slate-error;
            border-title-color: $slate-error; padding: 0 1; margin: 1 0 0 0; }
#recovery.-shown { display: block; }
#recovery.-lock { border: round $slate-warning; border-title-color: $slate-warning; }
#recovery-scroll { height: auto; max-height: 12; background: $slate-elevated; scrollbar-size-vertical: 1;
                   scrollbar-background: $slate-elevated; scrollbar-color: $slate-border; }
App.-short #recovery-scroll { max-height: 5; }
#recovery-command { color: $slate-text; height: auto; margin: 1 0 0 0; }
App.-narrow RunScreen.-recovering #phase-panel { display: none; }
/* Short terminals: while choices are shown they get the column; Inspect output swaps the report
   for the output pane and keeps the buttons on screen. */
App.-short RunScreen.-recovering #output-panel { display: none; }
App.-short RunScreen.-recovering #activity-panel { max-height: 100%; }
App.-short RunScreen.-recovering.-inspecting #output-panel { display: block; }
App.-short RunScreen.-inspecting #recovery-scroll, App.-short RunScreen.-inspecting #recovery-command { display: none; }
App.-narrow RunScreen.-recovering .gap { display: none; }
#recovery-text { color: $slate-text; height: auto; }
#recovery-buttons { layout: grid; grid-size: 2; grid-rows: 1; grid-gutter: 0 1; height: auto; margin: 1 0 0 0; }
#recovery-buttons Button { width: 100%; margin: 0; padding: 0 1; }

/* ---- results ---- */
#result-panel { width: 1fr; }
#result { background: $slate-panel; }

/* ---- dialogs ---- */
ModalScreen { background: $slate-bg 70%; align: center middle; }
.dialog {
    width: 72; max-width: 95%;
    height: auto; max-height: 90%;
    background: $slate-elevated;
    border: round $slate-accent;
    border-title-color: $slate-accent;
    border-title-style: bold;
    padding: 1 2;
}
.dialog .prose { color: $slate-text; }
.dialog-body { height: auto; max-height: 30; background: $slate-elevated; }
App.-short .dialog { padding: 0 1; }
App.-short .dialog-body { max-height: 14; }
.help-table { height: auto; color: $slate-muted; }

/* ---- small terminals ---- */
#too-small { display: none; layer: overlay; width: 100%; height: 100%; background: $slate-bg;
             content-align: center middle; text-align: center; color: $slate-warning; text-style: bold; }
App.-tiny #too-small { display: block; }
App.-tiny .body { display: none; }
App.-narrow #left-column { width: 28; }
App.-narrow #phase-panel { width: 34; }
App.-wide #left-column { width: 40; }
App.-wide #phase-panel { width: 58; }
App.-short #session-panel { display: none; }

/* ---- monochrome: selection and focus by reverse video, status by words ---- */
App:nocolor #nav > ListItem.-highlight { text-style: bold reverse; }
App:nocolor #phases > ListItem.-highlight { text-style: reverse; }
App:nocolor Button:focus { text-style: bold reverse; }
App:nocolor .panel:focus-within { border: heavy $slate-text; }

/* ---- ASCII-only terminals ---- */
App.-ascii .panel { border: ascii $slate-border; }
App.-ascii .panel:focus-within, App.-ascii .panel:focus { border: ascii $slate-accent; }
App.-ascii .dialog { border: ascii $slate-accent; }
App.-ascii #recovery { border: ascii $slate-error; }
App.-ascii #nav > ListItem.-highlight, App.-ascii #phases > ListItem.-highlight { border-left: blank; text-style: bold reverse; }
App.-ascii Input { border: ascii $slate-border; }
App.-ascii Input:focus { border: ascii $slate-accent; }
"""


# ---- ASCII-only terminals --------------------------------------------------------------------
from functools import lru_cache  # noqa: E402

from rich.cells import cell_len  # noqa: E402
from rich.segment import Segment  # noqa: E402
from textual.filter import LineFilter  # noqa: E402

_ASCII = str.maketrans({
    **{c: '-' for c in '─━┄┅┈┉╌╍═▔▁—–'}, **{c: '|' for c in '│┃┆┇┊┋╎╏║▏▕▎▍▌▐▊▋▉'},
    **{c: '+' for c in '┌┐└┘├┤┬┴┼╭╮╯╰┏┓┗┛┣┫┳┻╋╔╗╚╝╠╣╦╩╬▛▜▙▟▗▖▝▘'},
    **{c: '#' for c in '█▀▄■▆▇▅▃▂░▒▓'}, '·': '.', '…': '.', '•': '*', '●': '*', '○': 'o', '✓': 'x',
    '✗': '!', '▸': '>', '▶': '>', '◀': '<', '↑': '^', '↓': 'v', '←': '<', '→': '>', '×': 'x',
    ' ': ' ',
})


@lru_cache(maxsize=4096)
def asciify(text):
    """Single-cell replacements keep every column where it was; anything else unknown becomes '?'
    per cell (two for a wide character)."""
    text = text.translate(_ASCII)
    if text.isascii():
        return text
    return ''.join(ch if ch.isascii() else '?' * max(cell_len(ch), 1) for ch in text)


class AsciiFilter(LineFilter):
    """Render-time transliteration for terminals without UTF-8: borders, glyphs, Rich's ellipsis,
    toggle buttons and scrollbars all reach the screen as ASCII, column-for-column."""

    def apply(self, segments, background):
        return [segment if segment.control or segment.text.isascii()
                else Segment(asciify(segment.text), segment.style, segment.control) for segment in segments]
