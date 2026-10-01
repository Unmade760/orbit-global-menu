const template = [
  {
    label: 'Window',
    submenu: [
      ...(isMac ? [{ label: 'Bring All to Front', accelerator: 'Cmd+Alt+F' }] : [{ label: 'Always on Top', accelerator: 'Ctrl+Alt+T' }]),
    ],
  },
]
