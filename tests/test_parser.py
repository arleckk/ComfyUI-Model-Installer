"""Run with: python -B -m unittest discover -s tests -v"""

import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_cmi_parser_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
parser = importlib.import_module(f"{PACKAGE}.parser")


class MarkdownAssetTests(unittest.TestCase):
    def assets(self, text):
        workflow = {"nodes": [{
            "id": 1, "type": "MarkdownNote", "title": "Model Links", "widgets_values": [text],
        }]}
        return parser.collect_assets(workflow, include_inferred=False)

    def test_descriptive_label_uses_url_filename(self):
        assets = self.assets(
            "models/loras\n"
            "[Download the LoRA](https://huggingface.co/example/model/resolve/main/actual.safetensors?download=true)"
        )
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["name"], "actual.safetensors")
        self.assertEqual(assets[0]["directory"], "loras")

    def test_krea_style_note_keeps_models_and_ignores_support_links(self):
        assets = self.assets("""
models/diffusion_models
[Documentation](https://docs.comfy.org/tutorials/krea2)
[Download model](https://huggingface.co/example/krea2/resolve/main/krea2_turbo_fp8_scaled.safetensors)
[Report an issue](https://github.com/example/ComfyUI/issues)
models/loras
[Darkbrush LoRA](https://huggingface.co/example/krea2/resolve/main/krea2_darkbrush.safetensors)
models/text_encoders
[Text encoder](https://huggingface.co/example/krea2/resolve/main/qwen3vl_4b_fp8_scaled.safetensors)
models/vae
[VAE](https://huggingface.co/example/krea2/resolve/main/qwen_image_vae.safetensors)
[Examples](https://github.com/example/ComfyUI_examples)
""")
        self.assertEqual({(asset["directory"], asset["name"]) for asset in assets}, {
            ("diffusion_models", "krea2_turbo_fp8_scaled.safetensors"),
            ("loras", "krea2_darkbrush.safetensors"),
            ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors"),
            ("vae", "qwen_image_vae.safetensors"),
        })

    def test_bare_urls_accept_model_extensions_and_ignore_other_files(self):
        for extension in [".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft", ".model"]:
            with self.subTest(extension=extension):
                name = "model" + extension.upper()
                assets = self.assets(
                    f"models/loras\nhttps://example.com/{name}?download=true\n"
                    "https://example.com/README.md\nhttps://example.com/docs"
                )
                self.assertEqual([asset["name"] for asset in assets], [name])

    def test_explicit_filename_still_supports_extensionless_download_url(self):
        assets = self.assets("models/loras\n[example.safetensors](https://civitai.com/api/download/models/123)")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["name"], "example.safetensors")
        self.assertEqual(assets[0]["url"], "https://civitai.com/api/download/models/123")


if __name__ == "__main__":
    unittest.main()
