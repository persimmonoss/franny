import sys

from PyQt5.QtWidgets import QApplication

from .themes.palette import apply_theme
from .ui.main_window import FrannyBrowser


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app, "Dark")
    window = FrannyBrowser()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
