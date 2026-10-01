void Editor::setup()
{
    QAction *dup = actionCollection()->addAction(QStringLiteral("edit_duplicate"));
    dup->setText(i18n("Duplicate Line"));
    dup->setShortcut(QKeySequence::fromString(QStringLiteral("Ctrl+Alt+D")));
    QAction *join = actionCollection()->addAction(QStringLiteral("edit_join"));
    join->setText(i18n("Join Lines"));
    join->setShortcut(QStringLiteral("Ctrl+J"));
}
