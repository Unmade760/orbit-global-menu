registerAction2(class extends Action2 {
  constructor() {
    super({
      id: 'workbench.action.files.save',
      title: localize2('save', "Save"),
      keybinding: {
        weight: KeybindingWeight.WorkbenchContrib,
        primary: KeyMod.CtrlCmd | KeyCode.KeyS,
        linux: { primary: KeyMod.CtrlCmd | KeyMod.Alt | KeyCode.KeyS },
      },
    });
  }
});

KeybindingsRegistry.registerCommandAndKeybindingRule({
  id: 'workbench.action.openRecent',
  weight: KeybindingWeight.WorkbenchContrib,
  primary: KeyChord(KeyMod.CtrlCmd | KeyCode.KeyK, KeyMod.CtrlCmd | KeyCode.KeyR),
});

KeybindingsRegistry.registerCommandAndKeybindingRule({
  id: 'workbench.action.showCommands',
  primary: !isFirefox ? (KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyP) : undefined,
});
KeybindingsRegistry.registerCommandAndKeybindingRule({
  id: 'workbench.action.files.openFile',
  primary: isWeb ? KeyMod.CtrlCmd | KeyCode.KeyE : KeyMod.CtrlCmd | KeyCode.KeyO,
});
KeybindingsRegistry.registerCommandAndKeybindingRule({
  id: CLOSE_EDITOR_COMMAND_ID,
  primary: KeyMod.CtrlCmd | KeyCode.KeyW,
});
class FormatDocumentAction extends EditorAction {
  static readonly ID = 'editor.action.formatDocument';
  constructor() {
    super({
      id: FormatDocumentAction.ID,
      label: nls.localize2('formatDocument.label', "Format Document"),
      kbOpts: {
        primary: KeyMod.Shift + KeyMod.Alt + KeyCode.KeyF,
        linux: { primary: KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyI },
      },
    });
  }
}
