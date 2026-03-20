import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const PANEL_ID = "cmi-panel";
const STYLE_ID = "cmi-inline-style";
const TOP_GROUP_ID = "cmi-top-group";
const PLUGIN_NAME = "ComfyUI Model Installer";

function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);

    for (const [key, value] of Object.entries(attrs)) {
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "html") node.innerHTML = value;
        else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
        else if (key === "parent") value.appendChild(node);
        else if (key === "checked") node.checked = !!value;
        else if (key === "disabled") node.disabled = !!value;
        else node.setAttribute(key, value);
    }

    for (const child of children) {
        if (typeof child === "string") node.appendChild(document.createTextNode(child));
        else if (child) node.appendChild(child);
    }

    return node;
}

function ensureInlineStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
        .cmi-panel {
            position: fixed;
            top: 72px;
            right: 16px;
            width: 1180px;
            max-width: calc(100vw - 32px);
            height: 80vh;
            background: #151515;
            color: #f2f2f2;
            border: 1px solid #333;
            border-radius: 14px;
            z-index: 100000;
            display: none;
            flex-direction: column;
            box-shadow: 0 10px 30px rgba(0,0,0,.35);
            overflow: hidden;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .cmi-panel.open {
            display: flex;
        }

        .cmi-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 14px 16px;
            border-bottom: 1px solid #2b2b2b;
        }

        .cmi-header-left {
            display: flex;
            flex-direction: column;
            gap: 4px;
            min-width: 0;
        }

        .cmi-title {
            font-size: 16px;
            font-weight: 700;
        }

        .cmi-version {
            font-size: 12px;
            color: #9aa4b2;
        }

        .cmi-header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .cmi-close,
        .cmi-update-plugin-btn {
            border: 1px solid #444;
            background: #232323;
            color: #fff;
            border-radius: 8px;
            cursor: pointer;
        }

        .cmi-close {
            width: 32px;
            height: 32px;
        }

        .cmi-update-plugin-btn {
            height: 32px;
            padding: 0 12px;
            font-size: 12px;
            font-weight: 600;
        }

        .cmi-update-plugin-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .cmi-toolbar {
            display: flex;
            gap: 10px;
            padding: 12px 16px;
            border-bottom: 1px solid #2b2b2b;
            flex-wrap: wrap;
            align-items: center;
        }

        .cmi-toolbar button {
            border: 1px solid #444;
            background: #232323;
            color: #fff;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }

        .cmi-toolbar button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .cmi-toolbar .cmi-danger {
            background: #4b1f1f;
            border-color: #7f2d2d;
        }

        .cmi-toolbar .cmi-danger:hover {
            background: #622626;
        }

        .cmi-toggle {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #ccc;
            font-size: 12px;
            user-select: none;
        }

        .cmi-toggle input {
            cursor: pointer;
        }

        .cmi-summary {
            padding: 10px 16px;
            font-size: 13px;
            color: #ccc;
            border-bottom: 1px solid #2b2b2b;
        }

        .cmi-table-wrap {
            flex: 1;
            overflow: auto;
        }

        .cmi-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }

        .cmi-table th,
        .cmi-table td {
            border-bottom: 1px solid #262626;
            padding: 10px 8px;
            text-align: left;
            vertical-align: top;
            font-size: 12px;
        }

        .cmi-table th:nth-child(1),
        .cmi-table td:nth-child(1) { width: 36px; }

        .cmi-table th:nth-child(2),
        .cmi-table td:nth-child(2) { width: 250px; word-break: break-word; }

        .cmi-table th:nth-child(3),
        .cmi-table td:nth-child(3) { width: 110px; }

        .cmi-table th:nth-child(4),
        .cmi-table td:nth-child(4) { width: 100px; }

        .cmi-table th:nth-child(5),
        .cmi-table td:nth-child(5) { width: 130px; }

        .cmi-table th:nth-child(6),
        .cmi-table td:nth-child(6) { width: 95px; }

        .cmi-table th:nth-child(7),
        .cmi-table td:nth-child(7) { width: 115px; }

        .cmi-table th:nth-child(8),
        .cmi-table td:nth-child(8) { width: 180px; }

        .cmi-table th:nth-child(9),
        .cmi-table td:nth-child(9) { width: auto; word-break: break-word; }

        .cmi-progress-wrap {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .cmi-progress-bar {
            width: 100%;
            height: 8px;
            background: #262626;
            border-radius: 999px;
            overflow: hidden;
            border: 1px solid #333;
        }

        .cmi-progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #3b82f6 0%, #22c55e 100%);
            width: 0%;
            transition: width 0.2s ease;
        }

        .cmi-progress-text {
            font-size: 11px;
            color: #9aa4b2;
        }

        .cmi-log {
            border-top: 1px solid #2b2b2b;
            padding: 10px 16px;
            font-size: 12px;
            color: #9ad5ff;
            min-height: 44px;
            white-space: pre-wrap;
            word-break: break-word;
        }

        #cmi-fallback-button {
            margin-top: 8px;
        }
    `;
    document.head.appendChild(style);
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
        },
        ...options,
    });

    const data = await response.json();
    if (!response.ok || data.ok === false) {
        throw new Error(data.error || `Request failed: ${response.status}`);
    }
    return data;
}

function safeClone(value) {
    try {
        return JSON.parse(JSON.stringify(value));
    } catch {
        return value ?? null;
    }
}

function getWorkflowObject() {
    const nodes = app?.graph?._nodes;
    if (!Array.isArray(nodes)) {
        throw new Error("Unable to read nodes from app.graph._nodes");
    }

    return {
        nodes: nodes.map((node) => ({
            id: node.id,
            type: node.type || "",
            title: node.title || "",
            properties: safeClone(node.properties || {}),
            widgets_values: safeClone(node.widgets_values || []),
        })),
    };
}

function formatBytes(bytes) {
    const n = Number(bytes || 0);
    if (!n) return "0 B";

    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let value = n;

    while (value >= 1024 && i < units.length - 1) {
        value /= 1024;
        i++;
    }

    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[i]}`;
}

function shortCommit(hash) {
    return hash ? hash.slice(0, 7) : "-";
}

function clampPercent(n) {
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
}

function getAssetPercent(asset) {
    const downloaded = Number(asset?.downloaded_bytes || 0);
    const total = Number(asset?.total_bytes || 0);
    if (total <= 0) return 0;
    return clampPercent((downloaded / total) * 100);
}

function getDownloadedText(asset) {
    const downloaded = Number(asset?.downloaded_bytes || 0);
    const total = Number(asset?.total_bytes || 0);

    if (total > 0) {
        return `${formatBytes(downloaded)} / ${formatBytes(total)}`;
    }

    if (downloaded > 0) {
        return formatBytes(downloaded);
    }

    return "-";
}

function setVersionText(text) {
    const node = document.getElementById("cmi-version");
    if (node) node.textContent = text;
}

function getOnlyMissingEnabled() {
    return !!window.__CMI_ONLY_MISSING__;
}

function setOnlyMissingEnabled(value) {
    window.__CMI_ONLY_MISSING__ = !!value;
    const checkbox = document.getElementById("cmi-only-missing");
    if (checkbox) checkbox.checked = !!value;
}

function getCurrentJobId() {
    return window.__CMI_CURRENT_JOB_ID__ || "";
}

function setCurrentJobId(jobId) {
    window.__CMI_CURRENT_JOB_ID__ = jobId || "";
    updateCancelButtonState();
}

function updateCancelButtonState() {
    const btn = document.getElementById("cmi-cancel-job");
    if (!btn) return;
    btn.disabled = !getCurrentJobId();
}

async function refreshPluginVersionInfo() {
    try {
        const result = await apiJson("/model-installer/version");
        const version = result.version || "unknown";
        const commit = result.current_commit ? ` (${shortCommit(result.current_commit)})` : "";
        const gitHint = result.git_repo ? "" : " | non-git install";
        setVersionText(`v${version}${commit}${gitHint}`);
    } catch {
        setVersionText("version unavailable");
    }
}

function makePanel() {
    let panel = document.getElementById(PANEL_ID);
    if (panel) return panel;

    panel = el("div", { id: PANEL_ID, class: "cmi-panel" });

    const header = el("div", { class: "cmi-header" }, [
        el("div", { class: "cmi-header-left" }, [
            el("div", { class: "cmi-title", text: PLUGIN_NAME }),
            el("div", { id: "cmi-version", class: "cmi-version", text: "loading version..." }),
        ]),
        el("div", { class: "cmi-header-actions" }, [
            el("button", {
                id: "cmi-update-plugin",
                class: "cmi-update-plugin-btn",
                type: "button",
                text: "Update Plugin",
            }),
            el("button", { class: "cmi-close", type: "button", text: "×" }),
        ]),
    ]);

    const toolbar = el("div", { class: "cmi-toolbar" }, [
        el("button", { id: "cmi-scan", type: "button", text: "Scan Workflow" }),
        el("button", { id: "cmi-install-missing", type: "button", text: "Install Missing" }),
        el("button", { id: "cmi-select-missing", type: "button", text: "Select All Missing" }),
        el("button", { id: "cmi-refresh", type: "button", text: "Refresh" }),
        el("button", { id: "cmi-check-update", type: "button", text: "Check Plugin Update" }),
        el("button", {
            id: "cmi-cancel-job",
            type: "button",
            class: "cmi-danger",
            text: "Cancel Current Job",
            disabled: true,
        }),
        el("label", { class: "cmi-toggle" }, [
            el("input", {
                id: "cmi-only-missing",
                type: "checkbox",
                checked: false,
            }),
            el("span", { text: "Only Missing" }),
        ]),
    ]);

    const summary = el("div", { id: "cmi-summary", class: "cmi-summary", text: "No scan yet." });
    const log = el("div", { id: "cmi-log", class: "cmi-log", text: "Ready." });
    const tableWrap = el("div", { class: "cmi-table-wrap" });
    const table = el("table", { class: "cmi-table", id: "cmi-table" });

    table.innerHTML = `
        <thead>
            <tr>
                <th></th>
                <th>Name</th>
                <th>Type</th>
                <th>Source</th>
                <th>Status</th>
                <th>Size</th>
                <th>Downloaded</th>
                <th>Progress</th>
                <th>Target</th>
            </tr>
        </thead>
        <tbody id="cmi-tbody"></tbody>
    `;

    tableWrap.appendChild(table);
    panel.appendChild(header);
    panel.appendChild(toolbar);
    panel.appendChild(summary);
    panel.appendChild(tableWrap);
    panel.appendChild(log);
    document.body.appendChild(panel);

    header.querySelector(".cmi-close")?.addEventListener("click", () => {
        panel.classList.remove("open");
    });

    panel.querySelector("#cmi-scan")?.addEventListener("click", scanWorkflow);
    panel.querySelector("#cmi-install-missing")?.addEventListener("click", installMissing);
    panel.querySelector("#cmi-select-missing")?.addEventListener("click", selectAllMissing);
    panel.querySelector("#cmi-refresh")?.addEventListener("click", async () => {
        await refreshPluginVersionInfo();
        await scanWorkflow();
    });
    panel.querySelector("#cmi-check-update")?.addEventListener("click", checkPluginUpdate);
    panel.querySelector("#cmi-update-plugin")?.addEventListener("click", updatePlugin);
    panel.querySelector("#cmi-cancel-job")?.addEventListener("click", cancelCurrentJob);
    panel.querySelector("#cmi-only-missing")?.addEventListener("change", (e) => {
        setOnlyMissingEnabled(e.target.checked);
        renderAssets(getStoredAssets());
    });

    return panel;
}

function openPanel() {
    makePanel().classList.add("open");
}

function setLog(message) {
    const node = document.getElementById("cmi-log");
    if (node) node.textContent = message;
}

function setSummary(message) {
    const node = document.getElementById("cmi-summary");
    if (node) node.textContent = message;
}

function getStoredAssets() {
    return window.__CMI_ASSETS__ || [];
}

function setStoredAssets(assets) {
    window.__CMI_ASSETS__ = assets || [];
}

function selectAllMissing() {
    const tbody = document.getElementById("cmi-tbody");
    if (!tbody) return;

    const rows = [...tbody.querySelectorAll("tr")];
    let count = 0;

    for (const row of rows) {
        const checkbox = row.querySelector(".cmi-row-check");
        if (!checkbox) continue;

        try {
            const asset = JSON.parse(row.dataset.asset);
            const shouldSelect = asset.status === "missing";
            checkbox.checked = shouldSelect;
            if (shouldSelect) count++;
        } catch {
            checkbox.checked = false;
        }
    }

    setLog(`Selected ${count} missing asset${count === 1 ? "" : "s"}.`);
}

function renderAssets(assets) {
    const tbody = document.getElementById("cmi-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    const onlyMissing = getOnlyMissingEnabled();

    let installed = 0;
    let missing = 0;
    let visible = 0;

    for (const asset of assets) {
        if (asset.status === "installed" || asset.status === "already_installed") installed++;
        if (asset.status === "missing") missing++;

        if (onlyMissing && asset.status !== "missing" && asset.status !== "downloading") {
            continue;
        }

        visible++;

        const checkbox = el("input", {
            type: "checkbox",
            class: "cmi-row-check",
        });
        checkbox.checked = asset.status === "missing";

        let statusText = asset.status || "";
        const percent = getAssetPercent(asset);
        if (asset.status === "downloading" && Number(asset.total_bytes || 0) > 0) {
            statusText = `${asset.status} (${percent.toFixed(1)}%)`;
        }

        const sizeText = Number(asset.total_bytes || 0) > 0
            ? formatBytes(asset.total_bytes)
            : "-";

        const downloadedText = getDownloadedText(asset);

        const progressWrap = el("div", { class: "cmi-progress-wrap" }, [
            el("div", { class: "cmi-progress-bar" }, [
                el("div", {
                    class: "cmi-progress-fill",
                    style: {
                        width: `${percent}%`,
                    },
                }),
            ]),
            el("div", {
                class: "cmi-progress-text",
                text: Number(asset.total_bytes || 0) > 0 ? `${percent.toFixed(1)}%` : "-",
            }),
        ]);

        const tr = el("tr", {}, [
            el("td", {}, [checkbox]),
            el("td", { text: asset.name || "" }),
            el("td", { text: asset.directory || "" }),
            el("td", { text: asset.source || "" }),
            el("td", { text: statusText }),
            el("td", { text: sizeText }),
            el("td", { text: downloadedText }),
            el("td", {}, [progressWrap]),
            el("td", { title: asset.target_path || "", text: asset.target_path || "" }),
        ]);

        tr.dataset.asset = JSON.stringify(asset);
        tbody.appendChild(tr);
    }

    const filterText = onlyMissing ? ` | Visible: ${visible} (Only Missing)` : ` | Visible: ${visible}`;
    setSummary(`Required: ${assets.length} | Installed: ${installed} | Missing: ${missing}${filterText}`);
    updateCancelButtonState();
}

async function scanWorkflow() {
    try {
        setLog("Scanning workflow...");
        const workflow = getWorkflowObject();

        const result = await apiJson("/model-installer/scan", {
            method: "POST",
            body: JSON.stringify({ workflow }),
        });

        setStoredAssets(result.assets || []);
        renderAssets(result.assets || []);
        setLog(`Scan complete. Found ${result.count} assets.`);
        openPanel();
    } catch (error) {
        console.error(error);
        setLog(`Scan error: ${error.message}`);
        openPanel();
    }
}

function getSelectedAssets() {
    const tbody = document.getElementById("cmi-tbody");
    if (!tbody) return [];

    const rows = [...tbody.querySelectorAll("tr")];
    const selected = [];

    for (const row of rows) {
        const checkbox = row.querySelector(".cmi-row-check");
        if (!checkbox?.checked) continue;

        try {
            selected.push(JSON.parse(row.dataset.asset));
        } catch {}
    }

    return selected;
}

async function pollJob(jobId) {
    setCurrentJobId(jobId);

    const maxLoops = 3600;

    for (let i = 0; i < maxLoops; i++) {
        const result = await apiJson(`/model-installer/status?job_id=${encodeURIComponent(jobId)}`);
        const job = result.job;

        const updatedAssets = getStoredAssets().map((a) => {
            const match = (job.assets || []).find(
                (ja) => ja.name === a.name && ja.directory === a.directory
            );
            return match ? { ...a, ...match } : a;
        });

        setStoredAssets(updatedAssets);
        renderAssets(updatedAssets);

        const currentAsset = (job.assets || []).find((a) => a.name === job.current_asset);

        let extra = "";
        if (currentAsset) {
            const downloaded = Number(currentAsset.downloaded_bytes || 0);
            const total = Number(currentAsset.total_bytes || 0);

            if (total > 0) {
                const percent = ((downloaded / total) * 100).toFixed(1);
                extra = ` | Downloaded: ${formatBytes(downloaded)} / ${formatBytes(total)} (${percent}%)`;
            } else if (downloaded > 0) {
                extra = ` | Downloaded: ${formatBytes(downloaded)}`;
            }
        }

        const current = job.current_asset ? ` | Current: ${job.current_asset}` : "";
        setLog(`Job ${job.status} | Progress: ${job.completed_assets}/${job.total_assets}${current}${extra}`);

        if (
            job.status === "completed" ||
            job.status === "completed_with_errors" ||
            job.status === "cancelled"
        ) {
            break;
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    setCurrentJobId("");
    await scanWorkflow();
}

async function installMissing() {
    try {
        const selected = getSelectedAssets().filter((a) => a.status === "missing");

        if (!selected.length) {
            setLog("Nothing selected or no missing assets selected.");
            openPanel();
            return;
        }

        setLog(`Starting download for ${selected.length} assets...`);
        openPanel();

        const result = await apiJson("/model-installer/download", {
            method: "POST",
            body: JSON.stringify({
                assets: selected,
                overwrite: false,
            }),
        });

        await pollJob(result.job_id);
    } catch (error) {
        console.error(error);
        setLog(`Download error: ${error.message}`);
        setCurrentJobId("");
        openPanel();
    }
}

async function cancelCurrentJob() {
    const jobId = getCurrentJobId();
    if (!jobId) {
        setLog("No active job to cancel.");
        return;
    }

    try {
        setLog(`Cancelling job ${jobId}...`);
        await apiJson("/model-installer/cancel", {
            method: "POST",
            body: JSON.stringify({ job_id: jobId }),
        });
        setLog("Cancel requested. The current download will stop shortly.");
    } catch (error) {
        console.error(error);
        setLog(`Cancel error: ${error.message}`);
    }
}

async function checkPluginUpdate() {
    try {
        setLog("Checking plugin updates...");
        const result = await apiJson("/model-installer/update/check");
        await refreshPluginVersionInfo();

        if (!result.git_repo) {
            setLog("Plugin update check unavailable: this installation is not a git repository.");
            return;
        }

        if (!result.can_update) {
            setLog("Plugin update check is not available.");
            return;
        }

        if (result.has_update) {
            setLog(
                `Update available | local: ${shortCommit(result.current_commit)} | remote: ${shortCommit(result.remote_commit)}`
            );
        } else {
            setLog(`Plugin is already up to date (${shortCommit(result.current_commit)}).`);
        }
    } catch (error) {
        console.error(error);
        setLog(`Update check error: ${error.message}`);
    }
}

async function updatePlugin() {
    const button = document.getElementById("cmi-update-plugin");
    try {
        if (button) button.disabled = true;
        setLog("Updating plugin from origin/main...");

        const result = await apiJson("/model-installer/update/plugin", {
            method: "POST",
            body: JSON.stringify({}),
        });

        await refreshPluginVersionInfo();

        if (result.updated) {
            setLog(`${result.message}\nRestart ComfyUI to apply the updated frontend/backend.`);
        } else {
            setLog(result.message || "Plugin is already up to date.");
        }
    } catch (error) {
        console.error(error);
        setLog(`Plugin update error: ${error.message}`);
    } finally {
        if (button) button.disabled = false;
    }
}

function openInstaller() {
    openPanel();
}

async function openAndScanInstaller() {
    openPanel();
    await refreshPluginVersionInfo();
    await scanWorkflow();
}

async function installTopBarButton() {
    if (document.getElementById(TOP_GROUP_ID)) return true;

    try {
        const { ComfyButton } = await import("../../scripts/ui/components/button.js");
        const { ComfyButtonGroup } = await import("../../scripts/ui/components/buttonGroup.js");

        const mainButton = new ComfyButton({
            icon: "download",
            action: () => {
                openInstaller();
            },
            tooltip: PLUGIN_NAME,
            content: "Model Installer",
            classList: "comfyui-button comfyui-menu-mobile-collapse primary"
        }).element;

        const scanButton = new ComfyButton({
            icon: "magnify",
            action: async () => {
                await openAndScanInstaller();
            },
            tooltip: "Scan current workflow"
        }).element;

        const installButton = new ComfyButton({
            icon: "tray-arrow-down",
            action: async () => {
                openPanel();
                if (!getStoredAssets().length) {
                    await scanWorkflow();
                }
                await installMissing();
            },
            tooltip: "Install missing models"
        }).element;

        const updateButton = new ComfyButton({
            icon: "refresh",
            action: async () => {
                openPanel();
                await checkPluginUpdate();
            },
            tooltip: "Check plugin update"
        }).element;

        const group = new ComfyButtonGroup(
            mainButton,
            scanButton,
            installButton,
            updateButton
        );

        group.element.id = TOP_GROUP_ID;

        if (app.menu?.settingsGroup?.element) {
            app.menu.settingsGroup.element.before(group.element);
            console.log("[ComfyUI Model Installer] Top bar button attached");
            return true;
        }

        throw new Error("app.menu.settingsGroup.element not found");
    } catch (error) {
        console.warn("[ComfyUI Model Installer] New top bar API failed, using fallback button.", error);
        return false;
    }
}

function installFallbackMenuButton() {
    if (document.getElementById("cmi-fallback-button")) return true;

    const menu = document.querySelector(".comfy-menu");
    if (!menu) return false;

    const button = document.createElement("button");
    button.id = "cmi-fallback-button";
    button.textContent = "Model Installer";
    button.onclick = async () => {
        openPanel();
        await refreshPluginVersionInfo();
    };

    menu.append(button);
    console.log("[ComfyUI Model Installer] Fallback menu button attached");
    return true;
}

app.registerExtension({
    name: "ComfyUI.ModelInstaller",

    commands: [
        {
            id: "Comfy.ModelInstaller.Open",
            label: "Open Model Installer",
            function: async () => {
                openPanel();
                await refreshPluginVersionInfo();
            },
        },
        {
            id: "Comfy.ModelInstaller.Scan",
            label: "Scan Current Workflow",
            function: async () => await openAndScanInstaller(),
        },
        {
            id: "Comfy.ModelInstaller.InstallMissing",
            label: "Install Missing Models",
            function: async () => {
                openPanel();
                if (!getStoredAssets().length) {
                    await scanWorkflow();
                }
                await installMissing();
            },
        },
        {
            id: "Comfy.ModelInstaller.CheckPluginUpdate",
            label: "Check Plugin Update",
            function: async () => {
                openPanel();
                await checkPluginUpdate();
            },
        },
    ],

    async setup() {
        console.log("[ComfyUI Model Installer] Frontend loaded");
        ensureInlineStyles();
        makePanel();
        await refreshPluginVersionInfo();
        setOnlyMissingEnabled(false);
        updateCancelButtonState();

        const ok = await installTopBarButton();
        if (!ok) {
            installFallbackMenuButton();
        }
    },
});