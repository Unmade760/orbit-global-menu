#include <KActionCollection>
#include <KStandardAction>

void MainWindow::setupActions()
{
    KStandardAction::save(this, &MainWindow::save, actionCollection());
    KStandardActions::quit(this, &MainWindow::close, actionCollection());
    KStandardAction::create(KStandardAction::Find, this, SLOT(find()), actionCollection());

    QAction *a = actionCollection()->addAction(QStringLiteral("file_save_all"));
    a->setIcon(QIcon::fromTheme(QStringLiteral("document-save-all")));
    a->setText(i18n("Save A&ll"));
    actionCollection()->setDefaultShortcut(a, QKeySequence(Qt::CTRL | Qt::Key_L));

    a = actionCollection()->addAction(QStringLiteral("view_split_vert"));
    a->setText(i18nc("@action", "Split Ve&rtical"));
    actionCollection()->setDefaultShortcuts(a, {Qt::CTRL | Qt::SHIFT | Qt::Key_L, QKeySequence(QStringLiteral("Ctrl+K, Ctrl+V"))});

    QAction *copy = new QAction(tr("&Copy"), this);
    copy->setShortcut(QKeySequence::Copy);

    auto *reload = new QShortcut(QKeySequence(QStringLiteral("F5")), this);
    // a->setShortcut(QKeySequence(QStringLiteral("Ctrl+J")));
    const QKeySequence prefs = KStandardShortcut::preferences().first();
    fileMenu->addAction(tr("&Open..."), this, &MainWindow::open, QKeySequence::Open);
}

void MainWindow::setupMore()
{
    QAction *a = actionCollection()->addAction(QStringLiteral("file_close_all"));
    a->setText(i18n("Close A&ll"));
    auto *other = new QAction(i18n("Reload All"), this);
    actionCollection()->addAction(QStringLiteral("file_reload_all"), other);
}
