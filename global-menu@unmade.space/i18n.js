// Translation helpers for the shell and the preferences window alike. Both
// processes bind the "global-menu" domain from metadata.json at startup, so
// strings are translated where they are shown, never at import time. Plain
// GLib keeps this module loadable outside the shell, in the unit tests.

import GLib from 'gi://GLib';

const DOMAIN = 'global-menu';

export const _ = msgid => GLib.dgettext(DOMAIN, msgid);

export const ngettext = (singular, plural, n) => GLib.dngettext(DOMAIN, singular, plural, n);

// Marks a string for extraction where it is translated later, at use time
export const N_ = msgid => msgid;
