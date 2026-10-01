// Zettlr uses this menu on Linux too
export default function getMenu (sc: (id: string) => string) {
  return [
    {
      label: 'Edit',
      submenu: [
        { label: 'Filter files', accelerator: sc('filter-files') },
        { label: 'Copy as HTML', accelerator: 'Ctrl+Alt+C' },
      ],
    },
  ]
}
