import datetime
import json
import os
import platform
import random
import shutil
import tempfile
from collections import defaultdict

try:
    import keyring  # optional; used for secure passphrase storage if available
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False

from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtWebEngineWidgets import *
from PyQt5.QtWebEngineWidgets import QWebEngineDownloadItem, QWebEngineProfile, QWebEngineSettings
from PyQt5.QtGui import QIcon, QPalette, QColor, QFontMetrics, QKeySequence
from PyQt5.QtWidgets import QStyle, QProxyStyle, QShortcut
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QSlider
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor

from franny.browser.adblock import FrannyAdBlocker
from franny.browser.pdf_viewer import PDFViewerTab
from franny.browser.tabs import BrowserTab
from franny.storage.paths import BOOKMARKS_PATH, HISTORY_PATH, SYNC_CONFIG_PATH
from franny.sync.worker import SyncWorker
from franny.themes.palette import apply_theme
from franny.ui.tab_bar import GroupedTabBar
from franny.version import FRANNY_VERSION


# Franny main window
class FrannyBrowser(QMainWindow):
    def __init__(self, incognito=False):
        super().__init__()

        self.incognito = incognito
        self.setWindowTitle(f"Franny ({FRANNY_VERSION})" + (" [Incognito]" if self.incognito else ""))

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tab_bar = GroupedTabBar(self.tabs)
        self.tabs.setTabBar(self.tab_bar)
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b4b4b, stop:1 #2b2b2b);
                color: #ddd;
                padding: 10px 22px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 3px;
                font-weight: 500;
                min-width: 110px;
            }
            QTabBar::tab:selected {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a8cff, stop:1 #0069d9);
                color: white;
                font-weight: 700;
                margin-bottom: 0px;
            }
            QTabBar::tab:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d9cff, stop:1 #007acc);
                color: white;
            }
            QTabWidget::pane {
                border-top: 2px solid #1a8cff;
                background-color: #222;
            }
        """)

        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_address_bar)
        self.setCentralWidget(self.tabs)

        self.history = self.load_history()
        self.zoom_level = 1.0
        self.closed_tabs = []  # Stack for closed tabs
        self.tab_groups = {}  # tab index -> group name
        self.group_colors = {}  # group name -> color

        self.minimalist_mode = False  # Minimalist mode state

        self.init_toolbar()
        self.init_menu()
        self.init_shortcuts()
        self.init_bookmarks_bar()

        # Load sync settings and possibly start auto-sync
        self.load_sync_settings()
        if getattr(self, "sync_enabled", False):
            # default interval 10 minutes
            self.start_auto_sync(interval_minutes=10)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        # Initial tab: respect incognito flag
        if self.incognito:
            self.add_new_tab(QUrl("about:blank"), "New Tab")
        else:
            self.add_new_tab(QUrl("https://www.google.com"), "New Tab")

        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.show_tab_context_menu)

    # ---------- toolbar/menu/bookmarks/etc (unchanged) ----------
    def init_toolbar(self):
        self.toolbar = QToolBar("Navigation", self)
        self.toolbar.setIconSize(QSize(28, 28))
        self.toolbar.setStyleSheet("""
            QToolBar {
                background: #222;
                border-bottom: 1px solid #1a8cff;
                padding: 6px 10px;
                spacing: 10px;
            }
            QToolButton {
                background: transparent;
                border: none;
                padding: 5px;
            }
            QToolButton:hover {
                background: #1a8cff;
                border-radius: 4px;
            }
            QLineEdit {
                background: #333;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 6px 10px;
                color: #eee;
                min-width: 400px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #1a8cff;
                background: #222;
            }
        """)
        self.addToolBar(self.toolbar)

        back_btn = QAction(QIcon.fromTheme("go-previous"), "Back", self)
        back_btn.setToolTip("Go Back")
        back_btn.triggered.connect(lambda: self.current_browser().back())
        self.toolbar.addAction(back_btn)

        forward_btn = QAction(QIcon.fromTheme("go-next"), "Forward", self)
        forward_btn.setToolTip("Go Forward")
        forward_btn.triggered.connect(lambda: self.current_browser().forward())
        self.toolbar.addAction(forward_btn)

        reload_btn = QAction(QIcon.fromTheme("view-refresh"), "Reload", self)
        reload_btn.setToolTip("Reload Page")
        reload_btn.triggered.connect(lambda: self.current_browser().reload())
        self.toolbar.addAction(reload_btn)

        home_btn = QAction(QIcon.fromTheme("go-home"), "Home", self)
        home_btn.setToolTip("Go Home")
        home_btn.triggered.connect(self.go_home)
        self.toolbar.addAction(home_btn)

        self.toolbar.addSeparator()

        self.address_bar = QLineEdit(self)
        self.address_bar.returnPressed.connect(self.navigate_to_url)
        self.toolbar.addWidget(self.address_bar)

        new_tab_btn = QAction(QIcon.fromTheme("tab-new"), "New Tab", self)
        new_tab_btn.setToolTip("Open New Tab")
        new_tab_btn.triggered.connect(self.new_tab)
        self.toolbar.addAction(new_tab_btn)

    def init_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("Tabs and Modes")
        new_tab_action = QAction("New Tab", self)
        new_tab_action.triggered.connect(self.new_tab)
        file_menu.addAction(new_tab_action)

        restore_tab_action = QAction("Restore Closed Tab", self)
        restore_tab_action.setShortcut("Ctrl+Shift+T")
        restore_tab_action.triggered.connect(self.restore_closed_tab)
        file_menu.addAction(restore_tab_action)

        incognito_action = QAction("Incognito Mode", self)
        incognito_action.triggered.connect(self.toggle_incognito)
        file_menu.addAction(incognito_action)

        save_pdf_action = QAction("Save as PDF", self)
        save_pdf_action.triggered.connect(self.save_as_pdf)
        file_menu.addAction(save_pdf_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()
        clear_data_action = QAction("Clear Data", self)
        clear_data_action.triggered.connect(self.clear_data)
        file_menu.addAction(clear_data_action)

        # View menu
        view_menu = menu_bar.addMenu("View")
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.triggered.connect(self.zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.triggered.connect(self.zoom_out)
        view_menu.addAction(zoom_out_action)

        find_in_page_action = QAction("Find in Page", self)
        find_in_page_action.triggered.connect(self.find_in_page)
        view_menu.addAction(find_in_page_action)

        devtools_action = QAction("Open DevTools", self)
        devtools_action.setShortcut("F12")
        devtools_action.triggered.connect(lambda: self.current_browser().show_devtools())
        view_menu.addAction(devtools_action)

        minimalist_toggle_action = QAction("Toggle Minimalist Mode", self)
        minimalist_toggle_action.triggered.connect(self.toggle_minimalist_mode)
        view_menu.addAction(minimalist_toggle_action)

        resource_viewer_action = QAction("Site Resource Viewer", self)
        resource_viewer_action.triggered.connect(self.show_resource_viewer)
        view_menu.addAction(resource_viewer_action)

        # Bookmarks menu
        bookmarks_menu = menu_bar.addMenu("Bookmarks")
        add_bookmark_action = QAction("Add Bookmark", self)
        add_bookmark_action.triggered.connect(self.add_bookmark)
        bookmarks_menu.addAction(add_bookmark_action)

        import_bookmarks_action = QAction("Import Bookmarks", self)
        import_bookmarks_action.triggered.connect(self.import_bookmarks)
        bookmarks_menu.addAction(import_bookmarks_action)

        export_bookmarks_action = QAction("Export Bookmarks", self)
        export_bookmarks_action.triggered.connect(self.export_bookmarks)
        bookmarks_menu.addAction(export_bookmarks_action)

        self.bookmarks_action = QAction("Show Bookmarks", self)
        self.bookmarks_action.triggered.connect(self.show_bookmarks)
        bookmarks_menu.addAction(self.bookmarks_action)

        # Tools menu
        tools_menu = menu_bar.addMenu("Tools")
        download_manager_action = QAction("Download Manager", self)
        download_manager_action.triggered.connect(self.show_download_manager)
        tools_menu.addAction(download_manager_action)

        minimalist_toggle_action = QAction("Toggle Minimalist Mode", self)
        minimalist_toggle_action.triggered.connect(self.toggle_minimalist_mode)
        file_menu.addAction(minimalist_toggle_action)

        resource_viewer_action = QAction("Site Resource Viewer", self)
        resource_viewer_action.triggered.connect(self.show_resource_viewer)
        file_menu.addAction(resource_viewer_action)

    def init_bookmarks_bar(self):
        self.bookmarks_bar = QToolBar("Bookmarks Bar", self)
        self.bookmarks_bar.setIconSize(QSize(20, 20))
        self.bookmarks_bar.setStyleSheet("""
            QToolBar {
                background: #222;
                border-bottom: 1px solid #1a8cff;
                padding: 4px 6px;
            }
            QToolButton {
                background: transparent;
                border: none;
                color: #ccc;
                padding: 4px 10px;
                font-weight: 500;
            }
            QToolButton:hover {
                background: #1a8cff;
                color: white;
                border-radius: 4px;
            }
        """)
        self.addToolBar(Qt.TopToolBarArea, self.bookmarks_bar)
        self.update_bookmarks_bar()

    def update_bookmarks_bar(self):
        self.bookmarks_bar.clear()
        bookmarks = self.load_bookmarks()
        for url in bookmarks:
            action = QAction(QIcon.fromTheme("bookmark"), url, self)
            action.setToolTip(url)
            action.triggered.connect(lambda checked, u=url: self.add_new_tab(QUrl(u), u))
            self.bookmarks_bar.addAction(action)

    # ---------- tabs ----------
    def add_new_tab(self, qurl=None, label="New Tab"):
        # Special Franny URLs
        if qurl and qurl.toString().startswith("franny://"):
            url_str = qurl.toString()
            if url_str == "franny://version":
                widget = QWidget()
                layout = QVBoxLayout()
                layout.addWidget(QLabel(f"Franny Version: {FRANNY_VERSION}"))
                layout.addWidget(QLabel(f"Python: {platform.python_version()}"))
                layout.addWidget(QLabel(f"Qt: {QT_VERSION_STR}"))
                layout.addWidget(QLabel(f"PyQt: {PYQT_VERSION_STR}"))
                layout.addWidget(QLabel(f"Platform: {platform.platform()}"))
                
                widget.setLayout(layout)
                i = self.tabs.addTab(widget, "Version")
                self.tabs.setCurrentIndex(i)
                return
            elif url_str == "franny://newtab":
                self.add_new_tab(QUrl("https://www.google.com"), "New Tab")
                return
            elif url_str == "franny://mem":
                widget = QWidget()
                layout = QVBoxLayout()
                process = psutil.Process(os.getpid())
                mem_info = process.memory_info()
                layout.addWidget(QLabel(f"Memory Usage: {mem_info.rss // (1024*1024)} MB"))
                layout.addWidget(QLabel(f"Peak Memory: {mem_info.vms // (1024*1024)} MB"))
                layout.addWidget(QLabel(f"System Memory: {psutil.virtual_memory().percent}% used"))
                widget.setLayout(layout)
                i = self.tabs.addTab(widget, "Memory")
                self.tabs.setCurrentIndex(i)
                return
        # Normal tabs
        browser = BrowserTab(self)
        # If this browser is created for an incognito window, ensure its profile/settings are limited.
        if getattr(self, "incognito", False):
            try:
                browser.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
                p = browser.page().profile()
                p.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
                p.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
                try:
                    p.setPersistentStoragePath("")
                except Exception:
                    pass
            except Exception:
                pass

        browser.setUrl(qurl or QUrl("https://www.google.com"))
        i = self.tabs.addTab(browser, label)
        self.tabs.setCurrentIndex(i)
        browser.urlChanged.connect(lambda url, b=browser: self.update_tab_title(url, b))
        browser.urlChanged.connect(self.update_history)
        browser.titleChanged.connect(lambda title, b=browser: self.tabs.setTabText(self.tabs.indexOf(b), title))
        browser.iconChanged.connect(lambda icon, b=browser: self.tabs.setTabIcon(self.tabs.indexOf(b), icon))
        browser.loadFinished.connect(lambda: self.update_address_bar(self.tabs.currentIndex()))
        browser.page().profile().downloadRequested.connect(self.handle_download_requested)
        self.update_tab_group_styles()

    def new_tab(self):
        self.add_new_tab(QUrl("https://www.google.com"), "New Tab")

    def close_tab(self, index):
        if self.tabs.count() > 1:
            browser = self.tabs.widget(index)
            try:
                url = browser.url()
            except Exception:
                url = QUrl()
            try:
                title = browser.title()
            except Exception:
                title = "New Tab"
            self.closed_tabs.append((url, title))
            self.tabs.removeTab(index)
            browser.deleteLater()  # Free resources
        else:
            self.close()
        if index in self.tab_groups:
            del self.tab_groups[index]
        # Shift group indices after removal
        new_tab_groups = {}
        for idx, group in self.tab_groups.items():
            if idx > index:
                new_tab_groups[idx - 1] = group
            elif idx < index:
                new_tab_groups[idx] = group
        self.tab_groups = new_tab_groups
        self.update_tab_group_styles()

    def restore_closed_tab(self):
        if self.closed_tabs:
            url, title = self.closed_tabs.pop()
            self.add_new_tab(url, title)
        else:
            self.status_bar.showMessage("No closed tabs to restore.")

    def current_browser(self):
        return self.tabs.currentWidget()

    def update_tab_title(self, url, browser):
        if browser:
            self.tabs.setTabText(self.tabs.indexOf(browser), browser.title() or "New Tab")

    def update_address_bar(self, index):
        browser = self.tabs.widget(index)
        if browser:
            try:
                url = browser.url().toString()
                self.address_bar.setText(url)
                if url.startswith("https://"):
                    self.status_bar.showMessage("Secure connection (HTTPS)")
                elif url.startswith("http://"):
                    self.status_bar.showMessage("Not secure (HTTP)")
                elif url.startswith("ssh://"):
                    self.status_bar.showMessage("SSH protocol detected")
                else:
                    self.status_bar.clearMessage()
            except Exception:
                pass

    def navigate_to_url(self):
        url = QUrl(self.address_bar.text())
        if url.scheme() == "":
            url.setScheme("http")
        try:
            self.current_browser().setUrl(url)
        except Exception:
            pass

    def go_home(self):
        try:
            self.current_browser().setUrl(QUrl(getattr(self, "homepage", "https://www.google.com")))
        except Exception:
            pass

    def update_history(self, url):
        try:
            self.history.append(url.toString())
            self.save_history()
            self.status_bar.showMessage(f"Visited: {url.toString()}")
        except Exception:
            pass

    def toggle_incognito(self):
        # Open a new window in incognito mode so the current window remains intact.
        try:
            wnd = FrannyBrowser(incognito=True)
            # Keep a reference so it isn't garbage collected
            if not hasattr(self, "_child_windows"):
                self._child_windows = []
            self._child_windows.append(wnd)
            wnd.show()
            self.status_bar.showMessage("Opened Incognito Window")
        except Exception as e:
            self.status_bar.showMessage(f"Failed to open incognito window: {e}")

    def show_bookmarks(self):
        bookmarks = self.load_bookmarks()
        bookmark_dialog = QDialog(self)
        bookmark_dialog.setWindowTitle("Bookmarks")
        layout = QVBoxLayout()
        for bookmark in bookmarks:
            button = QPushButton(bookmark, self)
            favicon = QIcon()
            try:
                browser = BrowserTab()
                browser.setUrl(QUrl(bookmark))
                favicon = browser.icon()
            except Exception:
                pass
            button.setIcon(favicon)
            button.clicked.connect(lambda _, url=bookmark: self.add_new_tab(QUrl(url), url))
            layout.addWidget(button)
        bookmark_dialog.setLayout(layout)
        bookmark_dialog.exec_()

    def add_bookmark(self):
        current_url = ""
        try:
            current_url = self.current_browser().url().toString()
        except Exception:
            pass
        bookmarks = self.load_bookmarks()
        if current_url and current_url not in bookmarks:
            bookmarks.append(current_url)
            self.save_bookmarks(bookmarks)
            self.status_bar.showMessage(f"Bookmark added: {current_url}")
            self.update_bookmarks_bar()
        else:
            self.status_bar.showMessage("This page is already bookmarked or invalid.")

    def remove_bookmark(self, url):
        bookmarks = self.load_bookmarks()
        if url in bookmarks:
            bookmarks.remove(url)
            self.save_bookmarks(bookmarks)
            self.status_bar.showMessage(f"Bookmark removed: {url}")
            self.update_bookmarks_bar()
        else:
            self.status_bar.showMessage("Bookmark not found.")

    def load_bookmarks(self):
        if os.path.exists(BOOKMARKS_PATH):
            with open(BOOKMARKS_PATH, "r") as file:
                try:
                    return json.load(file)
                except Exception:
                    return []
        return []

    def save_bookmarks(self, bookmarks):
        os.makedirs(os.path.dirname(BOOKMARKS_PATH) or ".", exist_ok=True)
        with open(BOOKMARKS_PATH, "w") as file:
            json.dump(bookmarks, file)

    def save_history(self):
        os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)  # Ensure the config directory exists
        with open(HISTORY_PATH, "w") as file:
            json.dump(self.history, file)
            
    def load_history(self):
        if os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, "r") as file:
                    content = file.read().strip()
                    if not content:
                        return []
                    return json.loads(content)
            except Exception:
                return []
        return []

    def clear_data(self):
        try:
            self.history.clear()
            self.save_history()
            self.current_browser().page().profile().clearHttpCache()
            self.status_bar.showMessage("Browsing data cleared.")
        except Exception:
            pass

    def zoom_in(self):
        self.zoom_level += 0.1
        try:
            self.current_browser().setZoomFactor(self.zoom_level)
        except Exception:
            pass

    def zoom_out(self):
        self.zoom_level -= 0.1
        try:
            self.current_browser().setZoomFactor(self.zoom_level)
        except Exception:
            pass

    def find_in_page(self):
        search_text, ok = QInputDialog.getText(self, "Find in Page", "Enter text to find:")
        if ok and search_text:
            try:
                self.current_browser().findText(search_text, QWebEnginePage.FindFlags(QWebEnginePage.FindCaseSensitively))
            except Exception:
                pass

    def import_bookmarks(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Bookmarks", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, "r") as f:
                    imported = json.load(f)
                bookmarks = self.load_bookmarks()
                # Merge and deduplicate
                for url in imported:
                    if url not in bookmarks:
                        bookmarks.append(url)
                self.save_bookmarks(bookmarks)
                self.status_bar.showMessage("Bookmarks imported.")
            except Exception as e:
                self.status_bar.showMessage(f"Import failed: {e}")

    def export_bookmarks(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Bookmarks", "", "JSON Files (*.json)")
        if path:
            try:
                bookmarks = self.load_bookmarks()
                with open(path, "w") as f:
                    json.dump(bookmarks, f, indent=2)
                self.status_bar.showMessage("Bookmarks exported.")
            except Exception as e:
                self.status_bar.showMessage(f"Export failed: {e}")

    # ---------- downloads ----------
    def handle_download_requested(self, download: QWebEngineDownloadItem):
        save_path, _ = QFileDialog.getSaveFileName(self, "Save File", download.path())
        if save_path:
            download.setPath(save_path)
            download.accept()
            if not hasattr(self, "downloads"):
                self.downloads = []
            self.downloads.append(download)
            download.finished.connect(lambda: self.notify_download_finished(download))
            download.downloadProgress.connect(lambda rec, tot: self.update_download_manager())
            self.update_download_manager()

    def notify_download_finished(self, download):
        self.status_bar.showMessage(f"Download finished: {os.path.basename(download.path())}")

    def show_download_manager(self):
        if not hasattr(self, "downloads"):
            self.downloads = []
        dialog = QDialog(self)
        dialog.setWindowTitle("Download Manager")
        layout = QVBoxLayout()
        for download in self.downloads:
            status = "Finished" if download.isFinished() else "Downloading"
            progress = ""
            if not download.isFinished():
                try:
                    percent = int((download.receivedBytes() / max(download.totalBytes(), 1)) * 100)
                    progress = f" ({percent}%)"
                except Exception:
                    progress = ""
            label = QLabel(f"{os.path.basename(download.path())} - {status}{progress}")
            layout.addWidget(label)
            if download.isFinished():
                open_btn = QPushButton("Open File Location")
                open_btn.clicked.connect(lambda _, p=download.path(): os.startfile(os.path.dirname(p)))
                layout.addWidget(open_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def update_download_manager(self):
        pass

    # ---------- shortcuts ----------
    def init_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self.next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self.prev_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.new_tab)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.find_in_page)
        QShortcut(QKeySequence("Ctrl++"), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self.zoom_out)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.search_tabs)

        # Theme shortcuts from v21.1: Ctrl+Shift+1..N to switch themes
        for i, theme_name in enumerate(THEMES.keys(), start=1):
            # bind theme_name as default argument to avoid late-binding trap
            QShortcut(QKeySequence(f"Ctrl+Shift+{i}"), self, activated=(lambda t=theme_name: apply_theme(QApplication.instance(), t)))

    def next_tab(self):
        idx = self.tabs.currentIndex()
        count = self.tabs.count()
        self.tabs.setCurrentIndex((idx + 1) % count)

    def prev_tab(self):
        idx = self.tabs.currentIndex()
        count = self.tabs.count()
        self.tabs.setCurrentIndex((idx - 1) % count)

    # ---------- tab grouping ----------
    def show_tab_context_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        if index == -1:
            return
        menu = QMenu(self)
        create_group_action = QAction("Create New Group", self)
        create_group_action.triggered.connect(lambda: self.create_tab_group(index))
        menu.addAction(create_group_action)
        if self.group_colors:
            submenu = menu.addMenu("Add to Existing Group")
            for group in self.group_colors:
                act = QAction(group, self)
                act.triggered.connect(lambda checked, g=group: self.add_tab_to_group(index, g))
                submenu.addAction(act)
        if index in self.tab_groups:
            remove_action = QAction("Remove from Group", self)
            remove_action.triggered.connect(lambda: self.remove_tab_from_group(index))
            menu.addAction(remove_action)
        menu.exec_(self.tabs.tabBar().mapToGlobal(pos))

    def create_tab_group(self, index):
        group_name, ok = QInputDialog.getText(self, "New Tab Group", "Enter group name:")
        if ok and group_name:
            color = QColor(*random.sample(range(80, 220), 3)).name()
            self.group_colors[group_name] = color
            self.tab_groups[index] = group_name
            self.update_tab_group_styles()

    def add_tab_to_group(self, index, group_name):
        self.tab_groups[index] = group_name
        self.update_tab_group_styles()

    def remove_tab_from_group(self, index):
        if index in self.tab_groups:
            del self.tab_groups[index]
            self.update_tab_group_styles()

    def update_tab_group_styles(self):
        for idx in range(self.tabs.count()):
            group = self.tab_groups.get(idx)
            if group:
                self.tabs.tabBar().setTabData(idx, group)
            else:
                self.tabs.tabBar().setTabData(idx, None)
        self.tabs.tabBar().update()

    # ---------- PDF / settings ----------
    def save_as_pdf(self):
        browser = self.current_browser()
        if not browser:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save as PDF", "", "PDF Files (*.pdf)")
        if file_path:
            if not file_path.lower().endswith(".pdf"):
                file_path += ".pdf"
            def pdf_finished(path, ok):
                if ok:
                    self.status_bar.showMessage(f"Saved PDF: {path}")
                else:
                    self.status_bar.showMessage("Failed to save PDF.")
            browser.page().printToPdf(file_path, pageLayout=None, callback=lambda ok: pdf_finished(file_path, ok))

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        layout = QVBoxLayout()

        home_label = QLabel("Homepage URL:")
        home_input = QLineEdit(self)
        home_input.setText(getattr(self, "homepage", "https://www.google.com"))
        layout.addWidget(home_label)
        layout.addWidget(home_input)

        zoom_label = QLabel("Default Zoom:")
        zoom_slider = QSlider(Qt.Horizontal)
        zoom_slider.setRange(5, 20)
        zoom_slider.setValue(int(getattr(self, "zoom_level", 1.0) * 10))
        layout.addWidget(zoom_label)
        layout.addWidget(zoom_slider)

        theme_label = QLabel("Theme:")
        theme_combo = QComboBox()
        theme_combo.addItems(THEMES.keys())
        theme_combo.setCurrentText(getattr(self, "theme", "Dark"))
        layout.addWidget(theme_label)
        layout.addWidget(theme_combo)

        adblock_checkbox = QCheckBox("Enable Ad/Tracker Blocker")
        adblock_checkbox.setChecked(getattr(self, "adblock_enabled", False))
        layout.addWidget(adblock_checkbox)

        # Sync settings (MVP local encrypted store)
        sync_label = QLabel("Sync (experimental):")
        layout.addWidget(sync_label)
        self.sync_enabled_cb = QCheckBox("Enable Sync (local encrypted store)")
        self.sync_enabled_cb.setChecked(getattr(self, "sync_enabled", False))
        layout.addWidget(self.sync_enabled_cb)

        self.sync_pass_input = QLineEdit(self)
        self.sync_pass_input.setEchoMode(QLineEdit.Password)
        self.sync_pass_input.setPlaceholderText("Sync passphrase")
        layout.addWidget(self.sync_pass_input)

        test_sync_btn = QPushButton("Test Sync")
        test_sync_btn.clicked.connect(lambda: self.test_sync(home_input.text()))
        layout.addWidget(test_sync_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self.apply_settings(
            home_input.text(), zoom_slider.value() / 10, theme_combo.currentText(),
            adblock_checkbox.isChecked(), dialog))
        layout.addWidget(save_btn)

        # Save/close settings
        save_close_btn = QPushButton("Save & Close")
        save_close_btn.clicked.connect(lambda: self.apply_settings(
            home_input.text(), zoom_slider.value() / 10, theme_combo.currentText(),
            adblock_checkbox.isChecked(), dialog))
        layout.addWidget(save_close_btn)

        dialog.setLayout(layout)
        dialog.exec_()

    def apply_settings(self, homepage, zoom, theme, adblock_enabled, dialog):
        self.homepage = homepage
        self.zoom_level = zoom
        self.theme = theme
        try:
            self.current_browser().setZoomFactor(zoom)
        except Exception:
            pass
        apply_theme(QApplication.instance(), theme)
        self.adblock_enabled = adblock_enabled
        if adblock_enabled:
            self._adblocker = FrannyAdBlocker()
            for i in range(self.tabs.count()):
                browser = self.tabs.widget(i)
                browser.page().profile().setRequestInterceptor(self._adblocker)
        else:
            for i in range(self.tabs.count()):
                browser = self.tabs.widget(i)
                browser.page().profile().setRequestInterceptor(None)
        # Save sync-enabled preference and start/stop auto-sync
        self.sync_enabled = getattr(self, "sync_enabled_cb", None) and self.sync_enabled_cb.isChecked()
        if self.sync_enabled:
            # start periodic sync (10 minutes default)
            self.start_auto_sync(interval_minutes=10)
        else:
            self.stop_auto_sync()
        self.save_sync_settings()

        self.status_bar.showMessage("Settings applied.")
        dialog.accept()

    # ---------- SYNC helpers (new & improved) ----------
    def save_sync_settings(self):
        try:
            cfg = {
                "sync_enabled": getattr(self, "sync_enabled", False),
                "last_sync": getattr(self, "last_sync", None)
            }
            os.makedirs(os.path.dirname(SYNC_CONFIG_PATH) or ".", exist_ok=True)
            with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(SYNC_CONFIG_PATH) or ".") as tf:
                json.dump(cfg, tf)
                tf.flush()
                tmpname = tf.name
            shutil.move(tmpname, SYNC_CONFIG_PATH)
        except Exception:
            pass

    def load_sync_settings(self):
        try:
            path = SYNC_CONFIG_PATH
            if os.path.exists(path):
                with open(path, "r") as f:
                    cfg = json.load(f)
                self.sync_enabled = cfg.get("sync_enabled", False)
                self.last_sync = cfg.get("last_sync")
            else:
                self.sync_enabled = False
                self.last_sync = None
        except Exception:
            self.sync_enabled = False
            self.last_sync = None

    def _store_sync_passphrase(self, passphrase):
        if not passphrase:
            return False
        if _HAS_KEYRING:
            try:
                user = os.getenv("USER") or os.getenv("USERNAME") or "franny_user"
                keyring.set_password("franny_sync", user, passphrase)
                return True
            except Exception:
                return False
        return False

    def _get_stored_passphrase(self):
        if _HAS_KEYRING:
            try:
                user = os.getenv("USER") or os.getenv("USERNAME") or "franny_user"
                return keyring.get_password("franny_sync", user)
            except Exception:
                return None
        return None

    @staticmethod
    def _atomic_write_json(path, data):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(path) or ".") as tf:
            json.dump(data, tf, indent=2)
            tf.flush()
            tmpname = tf.name
        shutil.move(tmpname, path)

    def perform_sync(self, passphrase=None, direction="test"):
        """
        direction: "test" (roundtrip), "push" (local->remote), "pull" (remote->local), "sync" (merge both)
        Returns (ok: bool, message: str)
        This method runs in a worker thread (via SyncWorker).
        """
        try:
            # If passphrase not provided, try to load it from keyring or UI field
            if not passphrase:
                passphrase = self._get_stored_passphrase() if _HAS_KEYRING else None
            if not passphrase and getattr(self, "sync_pass_input", None):
                passphrase = self.sync_pass_input.text()
            if not passphrase:
                return (False, "No sync passphrase provided.")

            # Create SyncStore (wrap in try/except)
            try:
                from crypto.sync import SyncStore
            except Exception as e:
                return (False, f"Sync backend unavailable: {e}")

            store_path = os.path.join(os.path.expanduser("~"), ".franny_sync_store")
            try:
                store = SyncStore(store_path, passphrase)
            except Exception as e:
                return (False, f"Failed to open SyncStore: {e}")

            # Load local data to sync
            local_bookmarks = self.load_bookmarks()
            local_history = self.history[:] if hasattr(self, "history") else []

            now_ts = datetime.datetime.utcnow().isoformat() + "Z"

            # Basic test: write/read a test key
            if direction == "test":
                try:
                    store.set("franny_sync_test", {"ts": now_ts})
                    val = store.get("franny_sync_test")
                    if val and val.get("ts"):
                        # update last_sync in main thread via settings write (safe)
                        self.last_sync = now_ts
                        self.save_sync_settings()
                        return (True, "Sync test OK (local encrypted store).")
                    return (False, "Sync test failed: read-back mismatch.")
                except Exception as e:
                    return (False, f"Sync test failed: {e}")

            # Push local state
            if direction in ("push", "sync"):
                try:
                    # store bookmarks with timestamp
                    store.set("bookmarks", {"ts": now_ts, "data": local_bookmarks})
                    store.set("history", {"ts": now_ts, "data": local_history[-500:]})
                except Exception as e:
                    return (False, f"Failed to push data: {e}")

            # Pull remote state
            if direction in ("pull", "sync"):
                try:
                    remote_bookmarks = store.get("bookmarks") or {}
                    remote_history = store.get("history") or {}
                except Exception as e:
                    return (False, f"Failed to pull data: {e}")

                # Merge bookmarks: union by URL
                rb_data = remote_bookmarks.get("data", []) if isinstance(remote_bookmarks, dict) else []
                merged_bookmarks = list(dict.fromkeys((local_bookmarks or []) + (rb_data or [])))

                # Apply merged bookmarks atomically to disk and to memory
                try:
                    self._atomic_write_json(BOOKMARKS_PATH, merged_bookmarks)
                    # ensure in-memory state updated on main thread; write to disk succeeded
                    self.save_bookmarks(merged_bookmarks)
                except Exception as e:
                    return (False, f"Failed to write merged bookmarks: {e}")

                # Merge history: keep unique most recent up to N entries
                rh_data = remote_history.get("data", []) if isinstance(remote_history, dict) else []
                merged_history = []
                seen = set()
                # iterate from newest to oldest by reversing (assuming most recent appended at end)
                for item in reversed((local_history or []) + (rh_data or [])):
                    if item not in seen:
                        merged_history.append(item)
                        seen.add(item)
                merged_history = list(reversed(merged_history))[-1000:]
                try:
                    with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(HISTORY_PATH) or ".") as tf:
                        json.dump(merged_history, tf)
                        tf.flush()
                        tmpname = tf.name
                    shutil.move(tmpname, HISTORY_PATH)
                    self.history = merged_history
                except Exception as e:
                    return (False, f"Failed to write merged history: {e}")

            # success
            self.last_sync = now_ts
            try:
                self.save_sync_settings()
            except Exception:
                pass

            return (True, "Sync completed.")
        except Exception as e:
            return (False, f"Unexpected sync error: {e}")

    def test_sync(self, homepage=None):
        # Kick off a background sync test and update the UI when done.
        if not getattr(self, 'sync_enabled_cb', None) or not self.sync_enabled_cb.isChecked():
            self.status_bar.showMessage("Sync is disabled.")
            return

        passphrase = None
        if getattr(self, "sync_pass_input", None):
            passphrase = self.sync_pass_input.text() or None
        if not passphrase and _HAS_KEYRING:
            passphrase = self._get_stored_passphrase()

        if not passphrase:
            self.status_bar.showMessage("Set a sync passphrase first.")
            return

        # Optionally store passphrase securely if keyring available
        if _HAS_KEYRING:
            try:
                self._store_sync_passphrase(passphrase)
            except Exception:
                pass

        # Use QThreadPool to run perform_sync in background
        pool = QThreadPool.globalInstance()
        worker = SyncWorker(self.perform_sync, passphrase, "test")
        worker.signals.finished.connect(lambda ok, msg: self.status_bar.showMessage(msg))
        pool.start(worker)

    def start_auto_sync(self, interval_minutes=10):
        # Create a QTimer on the main thread to trigger periodic sync
        if hasattr(self, "_auto_sync_timer") and self._auto_sync_timer:
            self._auto_sync_timer.stop()
        self._auto_sync_timer = QTimer(self)
        self._auto_sync_timer.setInterval(max(1, interval_minutes) * 60 * 1000)
        self._auto_sync_timer.timeout.connect(lambda: self._trigger_background_sync_if_enabled())
        self._auto_sync_timer.start()

    def stop_auto_sync(self):
        if hasattr(self, "_auto_sync_timer") and self._auto_sync_timer:
            self._auto_sync_timer.stop()
            self._auto_sync_timer = None

    def _trigger_background_sync_if_enabled(self):
        if not getattr(self, "sync_enabled", False):
            return
        passphrase = getattr(self, "sync_pass_input", None) and self.sync_pass_input.text() or None
        if not passphrase and _HAS_KEYRING:
            passphrase = self._get_stored_passphrase()
        if not passphrase:
            # cannot run without passphrase
            self.status_bar.showMessage("Auto-sync skipped: no passphrase.")
            return
        pool = QThreadPool.globalInstance()
        worker = SyncWorker(self.perform_sync, passphrase, "sync")
        worker.signals.finished.connect(lambda ok, msg: self.status_bar.showMessage(msg))
        pool.start(worker)

    # ---------- remaining methods (toolbar customization, permissions, resource viewer, search) ----------
    def show_toolbar_customization(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Customize Toolbar")
        layout = QVBoxLayout()
        btns = []
        for action in self.toolbar.actions():
            cb = QCheckBox(action.text())
            cb.setChecked(action.isVisible())
            cb.stateChanged.connect(lambda state, a=action: a.setVisible(state == Qt.Checked))
            layout.addWidget(cb)
            btns.append(cb)
        dialog.setLayout(layout)
        dialog.exec_()

    def show_site_permissions(self):
        browser = self.current_browser()
        if not browser:
            return
        page = browser.page()
        dialog = QDialog(self)
        dialog.setWindowTitle("Site Permissions")
        layout = QVBoxLayout()
        for perm in [QWebEnginePage.PermissionCamera, QWebEnginePage.PermissionMicrophone, QWebEnginePage.PermissionNotifications]:
            label = QLabel(str(perm))
            btn = QPushButton("Toggle")
            btn.clicked.connect(lambda _, p=perm: page.setFeaturePermission(
                page.url(), p, QWebEnginePage.PermissionGrantedByUser))
            layout.addWidget(label)
            layout.addWidget(btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def toggle_minimalist_mode(self):
        self.minimalist_mode = not self.minimalist_mode
        if self.minimalist_mode:
            self.toolbar.hide()
            self.bookmarks_bar.hide()
            self.status_bar.hide()
            self.status_bar.showMessage("Minimalist Mode Enabled")
        else:
            self.toolbar.show()
            self.bookmarks_bar.show()
            self.status_bar.show()
            self.status_bar.showMessage("Minimalist Mode Disabled")

    def show_resource_viewer(self):
        browser = self.current_browser()
        if not browser:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Site Resource Viewer")
        layout = QVBoxLayout()
        resources_text = QTextEdit()
        resources_text.setReadOnly(True)
        layout.addWidget(resources_text)
        dialog.setLayout(layout)
        def show_resources():
            js_code = """
            (function() {
                var resources = {
                    images: [],
                    scripts: [],
                    stylesheets: []
                };
                document.querySelectorAll('img').forEach(img => resources.images.push(img.src));
                document.querySelectorAll('script').forEach(script => resources.scripts.push(script.src));
                document.querySelectorAll('link[rel="stylesheet"]').forEach(link => resources.stylesheets.push(link.href));
                return JSON.stringify(resources, null, 2);
            })();
            """
            browser.page().runJavaScript(js_code, lambda result: resources_text.setText(result))
        show_resources()
        dialog.exec_()

    def search_tabs(self):
        search_text, ok = QInputDialog.getText(self, "Search Tabs", "Enter search text:")
        if ok and search_text:
            results = []
            for i in range(self.tabs.count()):
                if search_text.lower() in self.tabs.tabText(i).lower():
                    results.append(i)
            if results:
                self.tabs.setCurrentIndex(results[0])
                self.status_bar.showMessage(f"Found {len(results)} matching tab(s)")
            else:
                self.status_bar.showMessage("No matching tabs found")

# --- Privacy & Security: Simple Ad/Tracker Blocker ---
