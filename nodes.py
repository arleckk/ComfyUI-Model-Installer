import json
from .parser import collect_assets


class ComfyUIModelInstallerInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "run"
    CATEGORY = "utils/model_installer"

    def run(self):
        return ("ComfyUI Model Installer loaded successfully",)


class ComfyUIModelInstallerScanWorkflow:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "hidden": {
                "prompt": "PROMPT",
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("assets_json", "count")
    FUNCTION = "run"
    CATEGORY = "utils/model_installer"

    def run(self, prompt=None):
        workflow = {}
        if isinstance(prompt, dict):
            workflow = prompt

        assets = collect_assets(workflow)
        return (json.dumps(assets, indent=2, ensure_ascii=False), len(assets))


NODE_CLASS_MAPPINGS = {
    "ComfyUIModelInstallerInfo": ComfyUIModelInstallerInfo,
    "ComfyUIModelInstallerScanWorkflow": ComfyUIModelInstallerScanWorkflow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ComfyUIModelInstallerInfo": "ComfyUI Model Installer Info",
    "ComfyUIModelInstallerScanWorkflow": "ComfyUI Model Installer Scan Workflow",
}