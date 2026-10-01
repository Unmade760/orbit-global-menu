impl ObjectSubclass for Window {
    fn class_init(klass: &mut Self::Class) {
        klass.add_binding_action(gdk::Key::w, gdk::ModifierType::CONTROL_MASK, "window.close");
    }
}

fn setup_accels(app: &adw::Application) {
    app.set_accels_for_action("app.quit", &["<primary>q"]);
}
