
import GLib from 'gi://GLib';

const DOMAIN = 'global-menu';

export const _ = msgid => GLib.dgettext(DOMAIN, msgid);

export const ngettext = (singular, plural, n) => GLib.dngettext(DOMAIN, singular, plural, n);

// marks a string for extraction and translated at use
export const N_ = msgid => msgid;
