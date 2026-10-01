"""Per-file state shared by the scanners: rows, menus, consumed spans."""

from . import accel
from .srctext import LineIndex


class FileScan:
    """Collects what one file declares.

    rows:     one shortcut each, {accel_raw, accel, label, action, file, line, kind}
              plus optional context, error and via (the standard table an
              accelerator was looked up in).
    menus:    menu trees the file defines.
    actions:  (action, label) pairs with no shortcut, used to label rows found
              elsewhere.
    consumed: source offsets already reported, so the generic literal passes
              do not report the same string twice.
    """

    def __init__(self, rel, text):
        self.rel = rel
        self.text = text
        self._lines = LineIndex(text)
        self.rows = []
        self.menus = []
        self.actions = []
        self.consumed = set()
        self.constants = {}

    def line(self, offset):
        return self._lines.line(offset)

    def _row(self, raw, accel_str, line, kind, label, action, context, error=None, via=None):
        row = {"accel_raw": raw, "accel": accel_str, "label": label, "action": action,
               "file": self.rel, "line": line, "kind": kind}
        if context:
            row["context"] = context
        if error:
            row["error"] = error
        if via:
            row["via"] = via
        self.rows.append(row)
        return row

    def add(self, raw, dialect, line, kind, label=None, action=None, context=None,
            keep_errors=True, split=True):
        """Normalize `raw` in `dialect` and add one row per alternative.

        Returns the rows added. With keep_errors False an alternative that
        does not normalize is dropped instead of reported with its error.
        """
        if split:
            results = accel.normalize_all(raw, dialect)
        else:
            results = [accel._one(raw, dialect)]
        added = []
        for result in results:
            if result.error and not keep_errors:
                continue
            added.append(self._row(result.raw if len(results) > 1 else raw, result.accel,
                                   line, kind, label, action, context, result.error))
        return added

    def add_seq(self, raw, seq, line, kind, label=None, action=None, context=None, via=None):
        return self._row(raw, accel.format_seq(seq), line, kind, label, action, context, via=via)

    def add_accel(self, raw, accel_str, line, kind, label=None, action=None, context=None,
                  error=None, via=None):
        """A row whose accelerator is already in the mapping grammar (or None)."""
        return self._row(raw, accel_str, line, kind, label, action, context, error, via)

    def add_error(self, raw, error, line, kind, label=None, action=None, context=None):
        return self._row(raw, None, line, kind, label, action, context, error)

    def add_action(self, action, label, line, kind, context=None):
        entry = {"action": action, "label": label, "file": self.rel, "line": line, "kind": kind}
        if context:
            entry["context"] = context
        self.actions.append(entry)

    def add_menu(self, menu):
        menu = {"file": self.rel, **menu}
        self.menus.append(menu)
        return menu


def seq_or_error(text, dialect):
    """(sequence, None) or (None, error) for one alternative."""
    result = accel._one(text, dialect)
    return result.seq, result.error
