# Shortcut mapping files

A mapping describes the menu bar to show for one application that does not
export a menu of its own. Every item carries a keyboard shortcut, and clicking
it sends that combination to the focused window.

Built-in mappings live in `global-menu@unmade.space/shortcuts/apps` and
must be listed in `shortcuts/index.json`. User mappings live in
`~/.config/global-menu/shortcuts/apps` and are picked up by being there.
A user file replaces the built-in with the same name outright, rather than
merging into it.

The extension reloads its mappings when the preferences save one. There is no
need to restart the session.

## File format

The file name without `.json` is the app id, and the `app` field has to repeat
it.

```json
{
  "format": 1,
  "app": "obsidian",
  "name": "Obsidian",
  "identifiers": ["obsidian.desktop", "obsidian", "md.obsidian.Obsidian"],
  "menus": [
    {
      "label": "File",
      "items": [
        {"label": "New Note", "shortcut": "<Ctrl>N"},
        {"separator": true},
        {"label": "Close Window", "shortcut": "<Ctrl><Shift>W"}
      ]
    }
  ]
}
```

`identifiers` are matched, lowercased, against the focused window's desktop
file id (with and without `.desktop`), its WM class, its WM class instance,
and the application name. The first mapping claiming an identifier wins, and a
conflict is reported in the journal.

A mapping with `"blank": true` and `"menus": []` gives the app no menu at all:
no app name, no fallback menus, and an exported menu is ignored. It is for
apps whose window is not a document window, such as a launcher's search box.

```json
{"format": 1, "app": "vicinae", "name": "Vicinae", "identifiers": ["vicinae.desktop", "vicinae"], "blank": true, "menus": []}
```

## Items

| Shape | Result |
| --- | --- |
| `{"label": "...", "shortcut": "..."}` | Sends the shortcut |
| `{"label": "..."}` | Greyed out, for actions with no usable shortcut |
| `{"separator": true}` | A separator line |
| `{"label": "...", "items": [...]}` | A submenu |

A placeholder is the honest thing to write when the application reaches an
action only through a menu of its own or a mouse gesture. Do not invent a
shortcut for it.

## Shortcut syntax

GTK accelerator strings: modifiers in angle brackets, then one key.

```
<Ctrl>N        <Ctrl><Shift>P        <Alt>F4        F11        Delete
```

Accepted modifiers are `<Ctrl>` (also `<Control>` and `<Primary>`),
`<Shift>`, `<Alt>` and `<Super>`. `<Meta>` is rejected because it means
different things on different setups.

The key is either one printable character or a keysym name: `F1` to `F12`,
`Return`, `Escape`, `Tab`, `BackSpace`, `Delete`, `Home`, `End`, `Page_Up`,
`Page_Down`, `Left`, `Up`, `Right`, `Down`, `Print`, `Insert`, `Menu`, `KP_0`
to `KP_9`, `KP_Decimal`, `KP_Add`, `KP_Subtract`, `KP_Multiply`, `KP_Divide`,
`KP_Enter`, and the X11 name of every ASCII punctuation character: `space`,
`exclam`, `quotedbl`, `numbersign`, `dollar`, `percent`, `ampersand`,
`apostrophe`, `parenleft`, `parenright`, `asterisk`, `plus`, `comma`, `minus`,
`period`, `slash`, `colon`, `semicolon`, `less`, `equal`, `greater`,
`question`, `at`, `bracketleft`, `backslash`, `bracketright`, `asciicircum`,
`underscore`, `grave`, `braceleft`, `bar`, `braceright`, `asciitilde`.

Punctuation can be written either way. `<Ctrl>/` and `<Ctrl>slash` are the
same shortcut.

A capital letter on its own is not Shift. Write `<Shift>a`, not `A`.

### Chord sequences

Separate chords with a space and they are sent in order, which covers
applications whose commands live behind a prefix key:

```json
{"label": "Save", "shortcut": "<Ctrl>x <Ctrl>s"}
{"label": "Save", "shortcut": ": w Return"}
{"label": "Go to Top", "shortcut": "g g"}
```

## Checking a file

Unparseable shortcuts drop the item and log a warning. To see them, turn on
**Debug shortcut menus** in preferences and watch:

```sh
journalctl -f -o cat /usr/bin/gnome-shell | grep global-menu
```
