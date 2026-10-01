#include <gtk/gtk.h>

static const struct {
  const char *action;
  const char *accels[3];
} accels[] = {
  { "win.new-tab", { "<Primary>t", NULL } },
  { "win.fullscreen", { "F11", NULL } },
};

static void
editor_window_class_init (EditorWindowClass *klass)
{
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  gtk_widget_class_add_binding_action (widget_class, GDK_KEY_s, GDK_CONTROL_MASK, "win.save", NULL);
  gtk_widget_class_add_binding_action (widget_class,
                                       GDK_KEY_s,
                                       GDK_CONTROL_MASK | GDK_SHIFT_MASK,
                                       "win.save-as", NULL);
  gtk_widget_class_add_binding (widget_class, GDK_KEY_Escape, 0, editor_window_escape_cb, NULL);
  /* gtk_widget_class_add_binding_action (widget_class, GDK_KEY_x, GDK_CONTROL_MASK, "win.dead", NULL); */
}

static void
editor_application_startup (GApplication *app)
{
  gtk_application_set_accels_for_action (GTK_APPLICATION (app), "app.quit",
                                         (const char *[]) { "<Primary>q", NULL });
  // gtk_application_set_accels_for_action (app, "app.old", (const char *[]) { "<Primary>j", NULL });
}

static void
editor_application_accels (GtkApplication *app)
{
  static const char *help_accels[] = { "F1", NULL };
  static const char *quit_accels[] = { "<Primary>q", "<Primary>w", NULL };

  gtk_application_set_accels_for_action (app, "app.help", help_accels);
  gtk_application_set_accels_for_action (app, "app.quit-all", quit_accels);
}
