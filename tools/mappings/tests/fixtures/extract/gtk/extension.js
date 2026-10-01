import Gdk from 'gi://Gdk';

export function setup(app, klass) {
    app.set_accels_for_action('win.go-back', ['<Alt>Left']);
    klass.add_binding_action(Gdk.KEY_l, Gdk.ModifierType.CONTROL_MASK, 'win.location', null);
}
