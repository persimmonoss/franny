from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtWidgets import QProxyStyle, QStyle, QStyleOptionTab, QStylePainter, QTabBar


class ChromiumTabStyle(QProxyStyle):
    def subControlRect(self, control, option, subControl, widget=None):
        rect = super().subControlRect(control, option, subControl, widget)
        if control == QStyle.CC_TabBar and subControl == QStyle.SC_TabBarTab:
            rect.setHeight(rect.height() + 8)
            rect.setWidth(rect.width() + 24)
            rect.adjust(-10, 0, 10, 0)
        return rect

    def drawControl(self, element, option, painter, widget=None):
        super().drawControl(element, option, painter, widget)


class GroupedTabBar(QTabBar):
    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()
        for i in range(self.count()):
            self.initStyleOption(opt, i)
            group = self.tabData(i)
            if group:
                color = self.parent().group_colors.get(group, "#888")
                opt.palette.setColor(QPalette.Window, QColor(color))
                opt.palette.setColor(QPalette.Button, QColor(color))
                opt.palette.setColor(QPalette.ButtonText, QColor("#fff"))
            painter.drawControl(QStyle.CE_TabBarTab, opt)
