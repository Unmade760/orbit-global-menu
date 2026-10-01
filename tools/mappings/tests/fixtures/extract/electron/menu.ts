import { app, Menu, MenuItemConstructorOptions } from 'electron'

const isMac = process.platform === 'darwin'

export function buildMenu(t: (key: string) => string): Menu {
  const template: MenuItemConstructorOptions[] = [
    {
      label: '&File',
      submenu: [
        { label: t('New Window'), accelerator: 'CmdOrCtrl+Shift+N', click: () => newWindow() },
        {
          label: 'Preferences…',
          accelerator: isMac ? 'Cmd+,' : 'Ctrl+,',
          click: openPreferences,
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        // { label: 'Dead', accelerator: 'CmdOrCtrl+J' },
        { label: 'Toggle Sidebar', accelerator: `CmdOrCtrl+B`, id: 'toggle-sidebar' },
      ],
    },
  ]
  return Menu.buildFromTemplate(template)
}

globalShortcut.register('CommandOrControl+Alt+K', () => {})
