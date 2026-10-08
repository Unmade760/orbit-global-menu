// Placement of the menu-bar buttons in the panel.
//
// All three menu sources put their buttons in one contiguous run at the left
// of the panel, app-name button first. The run cannot be addressed by
// absolute panel index: any extension that inserts a left-box button ahead of
// ours shifts the whole run right, while fixed indices keep inserting at the
// old spot, which is how the app name once ended up after the menus. Every
// insert is measured from where the run currently sits instead.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

/**
 * Panel index the run starts at: the app-name button when it exists,
 * otherwise the first menu button, otherwise the first free slot after the
 * workspace indicator.
 *
 * Anchoring on the app-name button also heals a run that is already out of
 * order, since menu buttons are placed after wherever it currently is.
 */
function runStart() {
	// _leftBox is private, but nothing public reports where a panel button
	// currently sits, and an absolute index is exactly what breaks here
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
 * Add a menu-bar button to the panel. `rank` is its place within the run:
 * 0 is the app-name button, menu buttons start at 1. Rank 1 is the run's
 * first slot when there is no app-name button, so the slot rank 0 would
 * have held is not skipped.
 *
 * @param {string} role - status area role, unique per button
 * @param {object} btn - the MenuBarButton to add
 * @param {number} rank - place within the run
 */
export function addBarButton(role, btn, rank) {
	const {index, hasAppName} = runStart();
	Main.panel.addToStatusArea(role, btn, index + (hasAppName ? rank : Math.max(rank - 1, 0)), 'left');
}
