static void
setup (GtkWidget *widget)
{
  GtkEventController *ctrl = gtk_shortcut_controller_new ();
  gtk_shortcut_controller_add_shortcut (GTK_SHORTCUT_CONTROLLER (ctrl),
    gtk_shortcut_new (gtk_keyval_trigger_new (GDK_KEY_r, GDK_CONTROL_MASK | GDK_SHIFT_MASK),
                      gtk_named_action_new ("win.reload-all")));
}
