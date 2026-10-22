
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

function runStart() {
	// _leftBox is private but no public api reports
	// where a panel button sits
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

export function addBarButton(role, btn, rank) {
	const {index, hasAppName} = runStart();
	Main.panel.addToStatusArea(role, btn, index + (hasAppName ? rank : Math.max(rank - 1, 0)), 'left');
}
