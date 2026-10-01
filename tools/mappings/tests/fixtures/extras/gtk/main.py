class App(Adw.Application):
    def __init__(self):
        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])
        self.create_action('about', self.on_about)
        self.create_action('win.search', self.on_search, shortcuts=['<primary>f'])
