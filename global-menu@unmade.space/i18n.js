// Translation helpers shared by the shell and preferences, which both bind the
// "global-menu" domain at startup.
// Strings are translated where shown, never at import time; plain GLib keeps
// this loadable in unit tests.

import GLib from 'gi://GLib';

const DOMAIN = 'global-menu';

export const _ = msgid => GLib.dgettext(DOMAIN, msgid);

export const ngettext = (singular, plural, n) => GLib.dngettext(DOMAIN, singular, plural, n);

// Marks a string for extraction where it is translated later, at use time
export const N_ = msgid => msgid;
