// Run with: node --test tests/model_installer_table.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

// Evaluate the actual extension; ComfyUI imports are stubbed and setup is not run.
const source = fs.readFileSync(path.join(__dirname, "../js/model_installer.js"), "utf8");

function tableContext() {
    class Element {
        constructor() { this.children = []; this.style = {}; this.dataset = {}; }
        set innerHTML(value) { this.children = []; }
        setAttribute(name, value) { this[name] = value; }
        appendChild(child) { this.children.push(child); }
        addEventListener() {}
    }
    const elements = new Map(["cmi-tbody", "cmi-summary", "cmi-cancel-job"].map(id => [id, new Element()]));
    const sandbox = vm.createContext({
        app: { registerExtension() {} }, api: {}, window: {},
        document: {
            getElementById: id => elements.get(id) || null,
            createElement: () => new Element(),
        },
        setTimeout: callback => callback(),
    });
    vm.runInContext(source.replace(/^import .*;\r?$/gm, ""), sandbox);
    return { sandbox, elements };
}

test("Only Missing keeps queued and active batch rows visible", () => {
    const { sandbox, elements } = tableContext();
    sandbox.setOnlyMissingEnabled(true);
    const statuses = ["missing", "pending", "downloading", "cancelling", "installed", "already_installed"];
    sandbox.renderAssets(statuses.map(status => ({ name: `${status}.safetensors`, status, directory: "loras" })));
    const rows = elements.get("cmi-tbody").children;
    assert.deepEqual(rows.map(row => row.children[1].textContent), statuses.slice(0, 4).map(status => `${status}.safetensors`));
});

test("polling retains queued targets and accepts the active download's actual destination", async () => {
    const { sandbox, elements } = tableContext();
    sandbox.setOnlyMissingEnabled(true);
    const assets = ["first", "second", "third"].map(name => ({
        name: `${name}.safetensors`, directory: "loras", status: "missing",
        target_path: `C:\\ComfyUI\\models\\loras\\${name}.safetensors`,
    }));
    sandbox.setStoredAssets(assets);
    const activePath = "D:\\shared-models\\first.safetensors";
    const job = {
        status: "running", total_assets: 3, completed_assets: 0,
        assets: assets.map((asset, index) => ({
            ...asset, status: index === 0 ? "downloading" : "pending",
            target_path: index === 0 ? activePath : "",
        })),
    };
    let requests = 0;
    sandbox.apiJson = async () => ({ job: { ...job, status: requests++ === 0 ? "running" : "cancelled" } });
    sandbox.scanWorkflow = async () => {};
    const renderedTargets = [];
    const renderAssets = sandbox.renderAssets;
    sandbox.renderAssets = updated => {
        renderAssets(updated);
        renderedTargets.push(elements.get("cmi-tbody").children.map(row => ({
            text: row.children[10].textContent, title: row.children[10].title,
        })));
    };
    await sandbox.pollJob("job-batch");
    assert.equal(renderedTargets[0].length, 3);
    assert.deepEqual(renderedTargets[0].map(target => target.text), [activePath, assets[1].target_path, assets[2].target_path]);
    assert.deepEqual(renderedTargets[0].map(target => target.title), renderedTargets[0].map(target => target.text));
});
