import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveScaffoldingTests(unittest.TestCase):
    def test_recommended_profile_is_explicitly_non_executable(self):
        module = load_script("validate_recommended_config")
        result = module.validate(ROOT / "config" / "recommended-h100-qwen32b.json")
        self.assertEqual(result, {"valid": True, "provider_calls": 0, "execution_ready": False})

    def test_gpu_capture_omits_sensitive_identifiers(self):
        module = load_script("capture_gpu_telemetry")
        self.assertNotIn("uuid", module.FIELDS)
        self.assertNotIn("serial", module.FIELDS)
        self.assertIn("utilization.gpu [%]", module.HEADERS)
        self.assertIn("memory.used [MiB]", module.HEADERS)
        output = "2026/09/21 12:00:00.000, 0, NVIDIA H100 80GB HBM3, 50, 70000, 81559, 500, 70\n"
        completed = type("Result", (), {"stdout": output})()
        with patch.object(module.subprocess, "run", return_value=completed):
            rows = module.sample()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), len(module.FIELDS))

    def test_planning_manifest_compiles_non_executable(self):
        module = load_script("compile_plan")
        manifest = json.loads((ROOT / "manifests" / "h100-qwen32b-planning.json").read_text())
        live_inputs = json.loads((ROOT / "examples" / "planning-live-inputs.json").read_text())
        plan = module.compile_plan(manifest, live_inputs)
        self.assertFalse(plan["execution_ready"])
        self.assertTrue(plan["manifest"]["planning_only"])

    def test_live_runner_parses_and_binds_repeated_cells(self):
        module = load_script("run_live_openai_benchmark")
        matrix = module.parse_matrix("128:1,2048:4")
        timeouts = module.parse_cell_timeouts("128:1:180,2048:4:300")
        contract = module.workload_contract(
            model="model", model_revision="revision", matrix=matrix,
            request_count=8, repetitions=3, seed=17,
        )
        plan = {
            "execution_ready": True,
            "manifest": {
                "planning_only": False,
                "model": {"repository": "model", "revision": "revision"},
                "runtimes": [{"id": "vllm"}],
                "workload": {"cells": [
                    {"input_tokens": 128, "concurrency": 1, "requests": 8,
                     "repetitions": 3, "output_tokens": 64, "timeout_seconds": 180},
                    {"input_tokens": 2048, "concurrency": 4, "requests": 8,
                     "repetitions": 3, "output_tokens": 64, "timeout_seconds": 300},
                ]},
                "execution": {
                    "model": {
                        "tokenizer_repository": "model",
                        "tokenizer_revision": "revision",
                        "chat_template": {"revision": "revision", "sha256": "0" * 64},
                    },
                    "runtimes": [{
                        "id": "vllm",
                        "dependencies": [{"name": "transformers", "version": "5.17.0"}],
                    }],
                    "workload": {
                        **contract,
                        "seed": 17,
                        "warmup_requests": 2,
                        "repetitions": 3,
                        "sampling": {"temperature": "0", "top_p": "1", "top_k": 0},
                        "load_mode": "closed-loop",
                    },
                },
            },
        }
        module.validate_workload_binding(
            plan, runtime="vllm", model="model", model_revision="revision",
            matrix=matrix, request_count=8, warmup_requests=2, repetitions=3,
            max_output_tokens=64, transformers_version="5.17.0",
            seed=17, cell_timeouts=timeouts,
        )
        with self.assertRaises(RuntimeError):
            module.validate_workload_binding(
                plan, runtime="vllm", model="model", model_revision="revision",
                matrix=matrix, request_count=8, warmup_requests=2, repetitions=2,
                max_output_tokens=64, transformers_version="5.17.0",
                seed=17, cell_timeouts=timeouts,
            )
        with self.assertRaises(RuntimeError):
            module.validate_workload_binding(
                plan, runtime="vllm", model="model", model_revision="revision",
                matrix=matrix, request_count=8, warmup_requests=2, repetitions=3,
                max_output_tokens=64, transformers_version="5.16.0",
                seed=17, cell_timeouts=timeouts,
            )

    def test_tokenizer_and_generated_prompt_contracts_fail_closed(self):
        module = load_script("run_live_openai_benchmark")
        tokenizer = type("Tokenizer", (), {"get_chat_template": lambda self: "exact-template"})()
        plan = {"manifest": {"execution": {"model": {
            "chat_template": {"sha256": "0" * 64}
        }}}}
        with self.assertRaises(RuntimeError):
            module.validate_tokenizer_contract(plan, tokenizer)
        contract = module.workload_contract(
            model="model", model_revision="revision", matrix=[(128, 1)],
            request_count=8, repetitions=3, seed=17,
        )
        changed = module.workload_contract(
            model="model", model_revision="revision", matrix=[(128, 1)],
            request_count=8, repetitions=3, seed=18,
        )
        self.assertNotEqual(
            contract["prompt_cells"][0]["prompt_sha256"],
            changed["prompt_cells"][0]["prompt_sha256"],
        )
    def test_live_runner_rejects_handwritten_or_digest_tampered_plan(self):
        module = load_script("validated_plan")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.json"
            path.write_text(json.dumps({"execution_ready": True, "manifest": {}}))
            with self.assertRaises(module.PlanValidationError):
                module.load_compiled_plan(path)

    def test_cell_deadline_is_injected_into_every_request(self):
        module = load_script("run_live_openai_benchmark")
        observed = []

        def stream(request):
            observed.append(request["absolute_deadline_ns"])
            return {
                "success": True,
                "text": "ok",
                "ttft_ms": 1,
                "output_tokens": 1,
            }

        before = time.monotonic_ns()
        result = module.run_cell(
            request_count=2,
            concurrency=1,
            cell_timeout_seconds=2,
            request={"_benchmark_input_tokens": 8},
            stream=stream,
        )
        self.assertEqual(result["summary"]["successful_requests"], 2)
        self.assertEqual(len(set(observed)), 1)
        self.assertGreater(observed[0], before)

if __name__ == "__main__":
    unittest.main()
