import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    Shortcut {
        sequence: "Ctrl+E"
        onActivated: editor.toggle()
    }
    Shortcut {
        sequences: [StandardKey.Copy, "Ctrl+Insert"]
        onActivated: copy()
    }
    Kirigami.Action {
        text: i18n("Open File…")
        shortcut: StandardKey.Open
    }
    Kirigami.Action {
        text: i18nc("@action", "New Tab")
        shortcut: "Ctrl+T"
    }
}
