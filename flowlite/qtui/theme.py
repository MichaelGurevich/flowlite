"""Design tokens measured from Wispr Flow's running hub window (light theme).

Palette values are the computed CSS custom properties (--sand-*, --vast-*, ...);
fonts are the same open-source families (Figtree for UI, EB Garamond for display),
bundled under flowlite/assets/fonts with their SIL OFL licences.
"""

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

ASSETS = Path(__file__).resolve().parent.parent / "assets"

SAND = {50: "#fcfcfb", 100: "#faf9f7", 200: "#f8f7f3", 300: "#f7f6f2", 400: "#f6f5f1",
        500: "#f5f4f0", 600: "#eeebe3", 700: "#c5c0b3", 800: "#a39d8e", 900: "#736e62",
        950: "#4d4a42"}
VAST = {50: "#e9e8e1", 100: "#deddd7", 200: "#c8c8c2", 300: "#b3b2ad", 400: "#9d9c98",
        500: "#878683", 600: "#71716e", 700: "#5b5b59", 800: "#464544", 900: "#30302f",
        950: "#1a1a1a"}
TEAL = {"dark": "#1a5c5c", "mid": "#369489", "light": "#84cdc1", "pale": "#ceedea", "empty": "#c5c0b3"}

BACKGROUND = SAND[50]          # page canvas
CHROME = SAND[500]             # window chrome / icon rail (#f5f4f0)
SECONDARY = SAND[600]          # borders, secondary surfaces
TERTIARY = SAND[500]           # cards in settings
CARD = "#ffffff"
LIST_BG = SAND[50]             # list cards share the canvas colour, with a border
FOREGROUND = VAST[950]
FOREGROUND_TERTIARY = VAST[600]
RING = SAND[950]
PRIMARY = VAST[950]
PRIMARY_FG = SAND[50]
RECORDING_BG = "#ecfdf5"
RECORDING_FG = "#059669"
ORANGE = "#ffa946"
PURPLE_BORDER = "#9b6fc4"
PURPLE_TINT = "#f7f2fb"
DANGER = "#ef4444"

UI_FAMILY = "Figtree"
DISPLAY_FAMILY = "EB Garamond"


def load_fonts():
    global UI_FAMILY, DISPLAY_FAMILY
    fonts = ASSETS / "fonts"
    families = set()
    for ttf in fonts.glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        families.update(QFontDatabase.applicationFontFamilies(fid))
    if "Figtree" not in families:
        UI_FAMILY = "Segoe UI"
    if "EB Garamond" not in families:
        DISPLAY_FAMILY = "Georgia"


def ui_font(px=14, weight=QFont.Weight.Normal):
    f = QFont(UI_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def display_font(px=36, italic=False):
    f = QFont(DISPLAY_FAMILY)
    f.setPixelSize(px)
    f.setItalic(italic)
    return f


def stylesheet():
    return f"""
    * {{ font-family: "{UI_FAMILY}", "Segoe UI"; color: {FOREGROUND}; }}
    QMainWindow, #Chrome {{ background: {CHROME}; }}
    #Canvas {{ background: {BACKGROUND}; border: 1px solid {SECONDARY}; border-radius: 16px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
    QScrollBar::handle:vertical {{ background: {SAND[700]}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QLabel#PageTitle {{ font-size: 24px; font-weight: 600; }}
    QLabel#SectionLabel {{ font-size: 12px; font-weight: 600; color: {SAND[950]}; letter-spacing: 1px; }}
    QLabel#Muted {{ color: {FOREGROUND_TERTIARY}; }}
    QPushButton#Primary {{ background: {PRIMARY}; color: {PRIMARY_FG}; border: none; border-radius: 8px;
                           padding: 10px 20px; font-size: 15px; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {VAST[800]}; }}
    QPushButton#Primary:disabled {{ background: {VAST[500]}; }}
    QPushButton#Secondary {{ background: {SECONDARY}; color: {FOREGROUND}; border: none; border-radius: 8px;
                             padding: 9px 22px; font-size: 15px; font-weight: 500; }}
    QPushButton#Secondary:hover {{ background: {SAND[700]}; }}
    QPushButton#Ghost {{ background: transparent; border: none; border-radius: 8px; padding: 6px 10px; }}
    QPushButton#Ghost:hover {{ background: {SECONDARY}; }}
    QPushButton#Tab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
                       padding: 6px 0 10px 0; margin-right: 26px; font-size: 15px; color: {SAND[950]}; }}
    QPushButton#Tab:checked {{ color: {FOREGROUND}; font-weight: 600; border-bottom: 2px solid {FOREGROUND}; }}
    QLineEdit, QTextEdit, QPlainTextEdit {{ background: {CARD}; border: 1px solid {SAND[700]}; border-radius: 8px;
                       padding: 9px 12px; font-size: 15px; selection-background-color: {SAND[700]}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1.5px solid {RING}; }}
    QComboBox {{ background: {CARD}; border: 1px solid {SECONDARY}; border-radius: 8px; padding: 8px 14px;
                 font-size: 15px; min-width: 160px; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {SECONDARY};
                                   selection-background-color: {SECONDARY}; selection-color: {FOREGROUND}; }}
    QToolTip {{ background: {VAST[950]}; color: {SAND[50]}; border: none; border-radius: 6px; padding: 5px 8px;
                font-size: 13px; }}
    QMenu {{ background: {CARD}; border: 1px solid {SECONDARY}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {SAND[500]}; }}
    """
