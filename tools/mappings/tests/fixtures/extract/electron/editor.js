const keymap = [
  { key: 'Mod-s', run: saveDocument },
  { key: 'Mod-Shift-z', run: redo },
]
const extraKeys = { 'Ctrl-/': toggleComment }
Mousetrap.bind('mod+k', openSearch)
