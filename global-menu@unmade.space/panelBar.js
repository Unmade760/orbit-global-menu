// Placement of the menu-bar buttons: one contiguous run at the left of the
// panel, app-name button first.
// Inserts are measured from where the run sits, since other extensions can
// shift it and fixed indices would drift.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

/** Panel index the run starts at: the app-name button, else the first menu button, else the first free slot after the workspace indicator. */
function runStart() {
	// _leftBox is private, but no public API reports where a panel button sits.
	const children = Main.panel._leftBox.get_children();
	const app = children.findIndex(c => c.first_child?._globalMenuAppName);
	if (app !== -1)
		return {index: app, hasAppName: true};
	const ours = children.findIndex(c => c.first_child?._globalMenuButton);
	if (ours !== -1)
		return {index: ours, hasAppName: false};
	const activities = Main.panel.statusArea.activities?.container;
	const at = activities ? children.indexOf(activities) : -1;
	return {index: at + 1, hasAppName: false};
}

/**
 * Add a menu-bar button to the panel. `rank` is its place in the run: 0 is the
 * app-name button, menu buttons start at 1.
 *
 * @param {string} role - status area role, unique per button
 * @param {object} btn - the MenuBarButton to add
 * @param {number} rank - place within the run
 */
export function addBarButton(role, btn, rank) {
	const {index, hasAppName} = runStart();
	Main.panel.addToStatusArea(role, btn, index + (hasAppName ? rank : Math.max(rank - 1, 0)), 'left');
}
