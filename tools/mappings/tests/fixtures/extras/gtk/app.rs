fn init(app: &RelmApp) {
    app.set_accelerators_for_action::<QuitAction>(&["<primary>q"]);
}
