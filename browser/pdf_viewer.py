from PyQt5.QtWebEngineWidgets import QWebEngineView


class PDFViewerTab(QWebEngineView):
    def __init__(self, pdf_url, parent=None):
        super().__init__(parent)
        self.setUrl(pdf_url)
        self.loadFinished.connect(self.inject_annotation_js)

    def inject_annotation_js(self):
        js_code = """
        (function() {
            if (document.getElementById('franny-pdf-annotator')) return;
            var canvas = document.createElement('canvas');
            canvas.id = 'franny-pdf-annotator';
            canvas.style.position = 'fixed';
            canvas.style.left = '0';
            canvas.style.top = '0';
            canvas.style.width = '100vw';
            canvas.style.height = '100vh';
            canvas.style.pointerEvents = 'auto';
            canvas.style.zIndex = 9999;
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            document.body.appendChild(canvas);

            var ctx = canvas.getContext('2d');
            var drawing = false;
            var lastX = 0, lastY = 0;

            function getXY(e) {
                if (e.touches) {
                    return [e.touches[0].clientX, e.touches[0].clientY];
                }
                return [e.clientX, e.clientY];
            }

            canvas.addEventListener('mousedown', function(e) {
                drawing = true;
                [lastX, lastY] = getXY(e);
            });
            canvas.addEventListener('mousemove', function(e) {
                if (!drawing) return;
                var [x, y] = getXY(e);
                ctx.strokeStyle = '#ffeb3b';
                ctx.lineWidth = 3;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(lastX, lastY);
                ctx.lineTo(x, y);
                ctx.stroke();
                [lastX, lastY] = [x, y];
            });
            canvas.addEventListener('mouseup', function(e) {
                drawing = false;
            });
            canvas.addEventListener('mouseleave', function(e) {
                drawing = false;
            });

            canvas.addEventListener('touchstart', function(e) {
                drawing = true;
                [lastX, lastY] = getXY(e);
            });
            canvas.addEventListener('touchmove', function(e) {
                if (!drawing) return;
                var [x, y] = getXY(e);
                ctx.strokeStyle = '#ffeb3b';
                ctx.lineWidth = 3;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(lastX, lastY);
                ctx.lineTo(x, y);
                ctx.stroke();
                [lastX, lastY] = [x, y];
                e.preventDefault();
            }, {passive: false});
            canvas.addEventListener('touchend', function(e) {
                drawing = false;
            });

            var btn = document.createElement('button');
            btn.textContent = 'Clear Annotations';
            btn.style.position = 'fixed';
            btn.style.top = '10px';
            btn.style.right = '10px';
            btn.style.zIndex = 10000;
            btn.style.background = '#222';
            btn.style.color = '#fff';
            btn.style.padding = '8px 16px';
            btn.style.border = 'none';
            btn.style.borderRadius = '6px';
            btn.style.cursor = 'pointer';
            btn.onclick = function() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            };
            document.body.appendChild(btn);

            var exportBtn = document.createElement('button');
            exportBtn.textContent = 'Export Annotations';
            exportBtn.style.position = 'fixed';
            exportBtn.style.top = '50px';
            exportBtn.style.right = '10px';
            exportBtn.style.zIndex = 10000;
            exportBtn.style.background = '#222';
            exportBtn.style.color = '#fff';
            exportBtn.style.padding = '8px 16px';
            exportBtn.style.border = 'none';
            exportBtn.style.borderRadius = '6px';
            exportBtn.style.cursor = 'pointer';
            exportBtn.onclick = function() {
                var canvas = document.getElementById('franny-pdf-annotator');
                var dataURL = canvas.toDataURL('image/png');
                var a = document.createElement('a');
                a.href = dataURL;
                a.download = 'annotations.png';
                a.click();
            };
            document.body.appendChild(exportBtn);

            window.addEventListener('resize', function() {
                var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
                ctx.putImageData(img, 0, 0);
            });
        })();
        """
        self.page().runJavaScript(js_code)
