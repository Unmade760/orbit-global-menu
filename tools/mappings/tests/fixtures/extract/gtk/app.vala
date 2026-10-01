public class App : Adw.Application {
    construct {
        set_accels_for_action ("app.about", {"F1"});
        add_binding_action (Gdk.Key.r, Gdk.ModifierType.CONTROL_MASK, "win.reload", null);
    }
}
