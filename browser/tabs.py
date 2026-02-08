from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebEngineWidgets import QWebEngineProfile, QWebEngineSettings


class BrowserTab(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        profile = self.page().profile()
        default_agent = profile.httpUserAgent()
        custom_agent = default_agent.replace(
            default_agent.split(" ")[0],
            "Franny/19.0.910",
        )
        profile.setHttpUserAgent(custom_agent)

        try:
            if parent and getattr(parent, "incognito", False):
                self.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
                profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
                profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
                try:
                    profile.setPersistentStoragePath("")
                except Exception:
                    pass
        except Exception:
            pass

        self.setUrl(QUrl("https://www.google.com"))
        self.page().fullScreenRequested.connect(self.handle_fullscreen_request)

    def handle_fullscreen_request(self, request):
        if request.toggleOn():
            self.window().showFullScreen()
        else:
            self.window().showNormal()
        request.accept()

    def show_devtools(self):
        if not hasattr(self, "devtools") or self.devtools is None:
            self.devtools = QWebEngineView()
            self.page().setDevToolsPage(self.devtools.page())
        self.devtools.show()

    def show_element_inspector(self):
        self.page().runJavaScript("inspect()")
