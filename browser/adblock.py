from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor


class FrannyAdBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, blocklist=None):
        super().__init__()
        self.blocklist = blocklist or [
            "doubleclick.net",
            "googlesyndication.com",
            "adservice.google.com",
            "ads.yahoo.com",
            "adnxs.com",
            "tracking",
            "analytics",
        ]

    def interceptRequest(self, info):
        url = info.requestUrl().toString()
        if any(bad in url for bad in self.blocklist):
            try:
                info.block(True)
            except Exception:
                pass
