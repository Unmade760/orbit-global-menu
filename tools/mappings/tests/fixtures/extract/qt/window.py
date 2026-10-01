from PyQt6.QtGui import QAction, QKeySequence, QShortcut


class Window:
    def build(self):
        save = QAction("&Save", self)
        save.setShortcut(QKeySequence("Ctrl+S"))
        quit_action = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self.search)
