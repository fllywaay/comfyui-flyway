import { app } from "../../scripts/app.js";

// Display-only rename: the underlying input/widget key stays "clear_directory"
// so saved workflows and existing links keep working after this ships. This
// only changes the text shown in the UI, whether it's a plain widget or has
// been converted to a socket (driven by an external logic node).
const LABELS = {
    FlywayH3MotionContextDir: {
        clear_directory: "前置清理",
    },
};

function applyLabels(node, map) {
    if (node.widgets) {
        for (const w of node.widgets) {
            if (map[w.name]) w.label = map[w.name];
        }
    }
    if (node.inputs) {
        for (const inp of node.inputs) {
            if (map[inp.name]) inp.label = map[inp.name];
        }
    }
}

app.registerExtension({
    name: "flyway.h3_motion_labels",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const map = LABELS[nodeData.name];
        if (!map) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            applyLabels(this, map);
            return r;
        };

        // Re-apply after "Convert widget to input" / "Convert input to widget",
        // since that rebuilds the widget/input list.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            applyLabels(this, map);
            return r;
        };
    },
});
