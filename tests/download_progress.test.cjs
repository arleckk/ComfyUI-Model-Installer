// Run with: node --test tests/download_progress.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

// Evaluate the actual extension; ComfyUI imports are stubbed and setup is not run.
const source = fs.readFileSync(path.join(__dirname, "../js/model_installer.js"), "utf8");
const context = vm.createContext({ app: { registerExtension() {} }, api: {} });
vm.runInContext(source.replace(/^import .*;\r?$/gm, ""), context);

function downloading(fields = {}) {
    return { status: "downloading", downloaded_bytes: 1024, total_bytes: 4096, ...fields };
}

test("live log includes bytes, percentage, speed, and ETA", () => {
    const asset = downloading({ speed_bytes_per_second: 1024, eta_seconds: 3 });
    assert.equal(context.buildDownloadProgressText(asset), " | Downloading 1.00 KB of 4.00 KB (25.0%) | 1.00 KB/s | ETA 3s");
});

test("copying is labeled separately", () => {
    const asset = downloading({ download_phase: "copying", speed_bytes_per_second: 1024, eta_seconds: 2 });
    assert.match(context.buildDownloadProgressText(asset), /^ \| Copying /);
});

test("unknown total reports bytes and speed without invented ETA", () => {
    const asset = downloading({ total_bytes: 0, speed_bytes_per_second: 512, eta_seconds: null });
    assert.equal(context.buildDownloadProgressText(asset), " | Downloading 1.00 KB | 512 B/s");
    assert.equal(context.getEtaText(asset), "-");
});

test("preparing download has visible feedback", () => {
    assert.equal(context.buildDownloadProgressText(downloading({ total_bytes: 0, downloaded_bytes: 0 })), " | Preparing download…");
});

test("received bytes remain visible while file completion is buffered", () => {
    const asset = downloading({ downloaded_bytes: 0, transferred_bytes: 2048, speed_bytes_per_second: 1024 });
    assert.equal(context.getProgressText(asset), "0.0% | 2.00 KB received");
    assert.match(context.buildDownloadProgressText(asset), /2\.00 KB received \| 1\.00 KB\/s/);
    assert.equal(context.getReceivedText({ ...asset, download_phase: "copying" }), "");
});

test("terminal states hide live metrics", () => {
    for (const status of ["installed", "already_installed", "error", "cancelling", "cancelled", "missing"]) {
        const asset = downloading({ status, speed_bytes_per_second: 100, eta_seconds: 5 });
        assert.equal(context.buildDownloadProgressText(asset), "");
        assert.equal(context.getSpeedText(asset), "-");
        assert.equal(context.getEtaText(asset), "-");
    }
});

test("ETA formats seconds, minutes, and hours", () => {
    for (const [seconds, label] of [[0, "0s"], [1.1, "2s"], [60, "1m 0s"], [125, "2m 5s"], [3661, "1h 1m"]]) {
        assert.equal(context.getEtaText(downloading({ eta_seconds: seconds })), label);
    }
});

test("invalid metrics do not show NaN or Infinity", () => {
    for (const value of [null, undefined, NaN, Infinity, -1]) {
        const asset = downloading({ speed_bytes_per_second: value, eta_seconds: value });
        assert.equal(context.getSpeedText(asset), "-");
        assert.equal(context.getEtaText(asset), "-");
    }
});

test("percentage cannot exceed 100 in the log", () => {
    assert.match(context.buildDownloadProgressText(downloading({ downloaded_bytes: 8000 })), /\(100\.0%\)/);
});

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

test("the table renders received bytes, speed and ETA in the progress cell", () => {
    const { sandbox, elements } = tableContext();
    const asset = downloading({
        name: "test.safetensors", directory: "loras", resolved: true,
        transferred_bytes: 2048, speed_bytes_per_second: 1024, eta_seconds: 3,
    });
    sandbox.renderAssets([asset]);
    const row = elements.get("cmi-tbody").children[0];
    const progress = row.children[8].children[0];
    assert.equal(progress.children[1].textContent, "25.0% | 2.00 KB received");
    assert.equal(progress.children[2].textContent, "Speed: 1.00 KB/s | ETA: 3s");
    assert.equal(row.children[5].textContent, "Downloading (25.0%)");
    sandbox.renderAssets([{ ...asset, download_phase: "copying" }]);
    assert.equal(elements.get("cmi-tbody").children[0].children[5].textContent, "Copying (25.0%)");
});

function cancellationContext() {
    const button = {};
    const log = {};
    const sandbox = vm.createContext({
        app: { registerExtension() {} }, api: {}, window: {},
        console: { error() {} },
        document: { getElementById: id => id === "cmi-cancel-job" ? button : id === "cmi-log" ? log : null },
    });
    vm.runInContext(source.replace(/^import .*;\r?$/gm, ""), sandbox);
    return { sandbox, button, log };
}

test("cancel disables repeat clicks while waiting for the backend", async () => {
    const { sandbox, button } = cancellationContext();
    sandbox.setCurrentJobId("job-test");
    let finishRequest;
    sandbox.apiJson = async () => new Promise(resolve => { finishRequest = resolve; });
    const cancelling = sandbox.cancelCurrentJob();
    assert.equal(button.disabled, true);
    assert.equal(button.textContent, "Cancelling…");
    finishRequest({ ok: true });
    await cancelling;
    assert.equal(sandbox.getCurrentJobId(), "job-test");
    sandbox.setCurrentJobId("");
    assert.equal(button.textContent, "Cancel Current Job");
});

test("a failed cancel request lets the user try again", async () => {
    const { sandbox, button, log } = cancellationContext();
    sandbox.setCurrentJobId("job-test");
    sandbox.apiJson = async () => { throw Error("Disconnected"); };
    await sandbox.cancelCurrentJob();
    assert.equal(button.disabled, false);
    assert.equal(button.textContent, "Cancel Current Job");
    assert.match(log.textContent, /Cancel error: Disconnected/);
});

test("job polling keeps the cancelled message after rescanning and releases the button", async () => {
    const { sandbox, button, log } = cancellationContext();
    const job = { status: "cancelled", cancel_requested: true, assets: [], total_assets: 1, completed_assets: 0 };
    sandbox.apiJson = async () => ({ job });
    sandbox.renderAssets = () => {};
    sandbox.scanWorkflow = async () => sandbox.setLog("Scan complete");
    await sandbox.pollJob("job-test");
    assert.equal(log.textContent, "Job cancelled.");
    assert.equal(sandbox.getCurrentJobId(), "");
    assert.equal(button.disabled, true);
    assert.equal(button.textContent, "Cancel Current Job");
    sandbox.setCurrentJobId("another-job");
    assert.equal(button.disabled, false);
});

test("a late cancel response does not overwrite the terminal message", async () => {
    const { sandbox, button, log } = cancellationContext();
    sandbox.setCurrentJobId("job-test");
    let finishRequest;
    sandbox.apiJson = async () => new Promise(resolve => { finishRequest = resolve; });
    const cancelling = sandbox.cancelCurrentJob();
    sandbox.setCurrentJobId("");
    sandbox.setLog("Job cancelled.");
    finishRequest({ ok: true });
    await cancelling;
    assert.equal(log.textContent, "Job cancelled.");
    assert.equal(button.disabled, true);
    assert.equal(button.textContent, "Cancel Current Job");
});
