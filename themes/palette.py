from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtWidgets import QApplication

from .theme_data import THEMES


def apply_theme(app: QApplication, theme_name: str):
    theme = THEMES.get(theme_name, THEMES["Dark"])
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(theme["window_bg"]))
    palette.setColor(QPalette.Base, QColor(theme["window_bg"]))
    palette.setColor(QPalette.WindowText, QColor(theme["toolbar_fg"]))
    palette.setColor(QPalette.Text, QColor(theme["toolbar_fg"]))
    palette.setColor(QPalette.Button, QColor(theme["toolbar_bg"]))
    palette.setColor(QPalette.ButtonText, QColor(theme["toolbar_fg"]))
    palette.setColor(QPalette.Highlight, QColor(theme["tab_selected_bg"]))
    palette.setColor(QPalette.HighlightedText, QColor(theme["tab_selected_fg"]))
    app.setPalette(palette)
