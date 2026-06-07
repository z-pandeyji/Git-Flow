from __future__ import annotations

import io
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from fastapi import HTTPException

from backend.app import api
from backend.app.analyzer import analyze_repo
from backend.app.flow_engine import build_flows
from backend.app.llm_service import _clean_ai_summary, summarize_flow
from backend.app.models import Repo, ScanRequest
from backend.app.pipeline import ARTIFACT_FILES, build_diagnostics, build_summary
from backend.app.risk_engine import find_risks
from backend.app.scanner import _sparse_paths, clone_public_repo, create_demo_repo, validate_public_github_url
from backend.app.storage import load_scan, save_result, scan_dir
from backend.app.models import AnalysisResult


class AnalysisTest(unittest.TestCase):
    def test_demo_repo_produces_evidence_backed_business_flows(self):
        repo = create_demo_repo()
        analysis = analyze_repo(repo)
        flows = build_flows(analysis)
        risks = find_risks(analysis)

        self.assertEqual(repo.name, "BusinessFlow Demo")
        self.assertEqual(repo.url, "demo://business-flow")
        self.assertEqual(analysis.overview.classification["dominantType"], "Business Application")
        self.assertGreaterEqual(analysis.overview.counts["routes"], 2)
        self.assertTrue(flows)
        self.assertTrue(all(flow.evidence_ids for flow in flows))
        self.assertTrue(all(step.evidence_id for flow in flows for step in flow.steps))
        self.assertTrue(all(flow.confidence_score > 0 for flow in flows))
        self.assertTrue(all(flow.confidence_label in {"Low", "Medium", "High", "Very High"} for flow in flows))
        self.assertTrue(all(flow.evidence_count >= 1 for flow in flows))
        self.assertTrue(all(flow.source_files for flow in flows))
        self.assertTrue(all(flow.source_locations for flow in flows))
        self.assertTrue(all(flow.answer for flow in flows))
        self.assertTrue(all(flow.trigger for flow in flows))
        self.assertTrue(all(step.actor and step.action and step.target for flow in flows for step in flow.steps))
        self.assertTrue(all(step.narrative for flow in flows for step in flow.steps))
        self.assertTrue(any(risk.category == "missing-validation" for risk in risks))
        intake_flow = next(flow for flow in flows if flow.name == "Intake Flow")
        review_flow = next(flow for flow in flows if flow.name == "Review Flow")
        self.assertIn("src/intake.service.ts", intake_flow.source_files)
        self.assertNotIn("src/intake.service.ts", review_flow.source_files)
        self.assertIn("Client sends POST /intake", intake_flow.answer)
        self.assertIn("Database state may change", intake_flow.side_effects)

    def test_validate_public_github_url_rejects_non_github(self):
        with self.assertRaisesRegex(ValueError, "public GitHub"):
            validate_public_github_url("https://example.com/not/github")

    def test_node_runtime_repo_uses_runtime_flows_from_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "nodejs-node-test"
            (root / "src").mkdir(parents=True)
            (root / "lib/internal/modules/cjs").mkdir(parents=True)
            (root / "lib/internal/process").mkdir(parents=True)
            (root / ".configurations").mkdir(parents=True)
            (root / "src/node.cc").write_text("void Start(int argc) {\n}\n", encoding="utf-8")
            (root / "src/env.cc").write_text("void RunTimers() {\n}\n", encoding="utf-8")
            (root / "lib/internal/modules/cjs/loader.js").write_text("function ModuleLoad() {\n  return true\n}\n", encoding="utf-8")
            (root / "lib/internal/process/task_queues.js").write_text("function runNextTicks() {\n  return true\n}\n", encoding="utf-8")
            (root / ".configurations/configuration.dsc.yaml").write_text("resources: []\n", encoding="utf-8")
            repo = Repo(id="nodejs-node-test", url="https://github.com/nodejs/node", name="node", owner="nodejs", local_path=str(root))

            analysis = analyze_repo(repo)
            flows = build_flows(analysis)

            self.assertEqual(analysis.overview.classification["dominantType"], "Runtime")
            self.assertGreaterEqual(len(flows), 2)
            self.assertIn("Runtime Bootstrap Flow", {flow.name for flow in flows})
            self.assertTrue(all(not step.technical_label.endswith(".yaml") for flow in flows for step in flow.steps))

    def test_pipeline_diagnostics_and_artifacts_follow_output_contract(self):
        repo = create_demo_repo()
        analysis = analyze_repo(repo)
        flows = build_flows(analysis)
        risks = find_risks(analysis)
        diagnostics = build_diagnostics(analysis, len(flows), any(flow.ai_summary_available for flow in flows))
        summary = build_summary(analysis, len(flows), len(risks), False)
        result = AnalysisResult(overview=analysis.overview, structure=analysis.structure, flows=flows, risks=risks, evidence=analysis.evidence, diagnostics=diagnostics, summary=summary)

        save_result("test-artifacts", result)

        self.assertEqual(diagnostics.artifactFiles, ARTIFACT_FILES)
        self.assertEqual([stage.label for stage in diagnostics.pipeline], ["fetch", "classify repository", "build structure graph", "detect execution paths", "generate behavior flows", "calculate confidence", "rank risks", "persist artifacts"])
        for filename in ARTIFACT_FILES:
            self.assertTrue((scan_dir("test-artifacts") / filename).exists(), filename)

    def test_supported_repository_types_select_analysis_strategy(self):
        cases = [
            ("app", {"package.json": '{"dependencies":{"express":"latest"}}', "src/app.ts": "import express from 'express'; const app = express(); app.post('/signup', () => true);"}, "Business Application", "Business Flows"),
            ("infra", {"Dockerfile": "FROM python:3.12\n", "main.tf": "resource \"x\" \"y\" {}\n"}, "Infrastructure", "System Flows"),
            ("cli", {"bin/tool.js": "function runCommand() { return true }\n"}, "CLI", "Command Execution Flows"),
            ("library", {"src/index.ts": "export function useThing() { return true }\n"}, "Library", "Usage Flows"),
        ]
        with TemporaryDirectory() as tmp:
            for name, files, expected_type, expected_strategy in cases:
                root = Path(tmp) / name
                root.mkdir()
                for relative, content in files.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                analysis = analyze_repo(Repo(id=name, url=f"demo://{name}", name=name, local_path=str(root)))
                self.assertEqual(analysis.overview.classification["dominantType"], expected_type)
                self.assertEqual(analysis.overview.classification["analysisStrategy"], expected_strategy)

    def test_evidence_first_filters_claims_without_evidence(self):
        repo = create_demo_repo()
        analysis = analyze_repo(repo)
        analysis.evidence.clear()

        self.assertEqual(build_flows(analysis), [])
        self.assertEqual(find_risks(analysis), [])

    def test_docs_and_config_are_parsed_not_unknowns(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "docs-config"
            root.mkdir()
            (root / "README.md").write_text("# Project\n\nReadable docs.\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies":{"express":"latest"}}\n', encoding="utf-8")
            (root / "src").mkdir()
            (root / "src/index.ts").write_text("export function start() { return true }\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="docs-config", url="demo://docs", name="docs", local_path=str(root)))
            diagnostics = build_diagnostics(analysis, 0, False)

            self.assertEqual(diagnostics.coverage.filesParsed, 100)
            self.assertEqual(diagnostics.unknowns.filesNotParsed, [])
            self.assertEqual(diagnostics.unknowns.unsupportedSyntax, [])

    def test_dockerfile_does_not_force_infrastructure_when_code_exists(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "code-with-docker"
            root.mkdir()
            (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
            (root / "bin").mkdir()
            (root / "bin/headroom.py").write_text("def main():\n    return True\n", encoding="utf-8")
            (root / "crates/headroom-core/src").mkdir(parents=True)
            (root / "crates/headroom-core/src/lib.rs").write_text("pub fn trim() {}\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="code-with-docker", url="demo://code", name="code", local_path=str(root)))

            self.assertNotEqual(analysis.overview.classification["dominantType"], "Infrastructure")
            self.assertEqual(analysis.overview.classification["analysisStrategy"], "Command Execution Flows")

    def test_benchmark_and_test_content_do_not_create_random_god_service_risks(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "risk-noise"
            (root / "benchmarks").mkdir(parents=True)
            noisy = "\n".join(f"def helper_{index}():\n    return 'service text'\n" for index in range(40))
            (root / "benchmarks/service_benchmark.py").write_text(noisy, encoding="utf-8")
            (root / "src").mkdir()
            (root / "src/real_service.py").write_text("def handle():\n    return True\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="risk-noise", url="demo://risk", name="risk", local_path=str(root)))
            risks = find_risks(analysis)

            self.assertFalse(any("benchmarks/" in source for risk in risks for source in risk.source_files))

    def test_ai_disabled_never_calls_ollama(self):
        old_value = os.environ.pop("BFO_ENABLE_AI", None)
        try:
            with patch("backend.app.llm_service.urllib.request.urlopen") as urlopen:
                summary, available = summarize_flow("Booking Flow", ["API request", "service"])
        finally:
            if old_value is not None:
                os.environ["BFO_ENABLE_AI"] = old_value

        self.assertFalse(available)
        self.assertIn("AI summary unavailable", summary)
        urlopen.assert_not_called()

    def test_candidate_flow_uses_optional_ai_summary_when_available(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "cli-tool"
            (root / "bin").mkdir(parents=True)
            (root / "bin/tool.py").write_text("def main():\n    return True\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="cli-tool", url="demo://cli", name="cli", local_path=str(root)))
            with patch("backend.app.flow_engine.summarize_flow", return_value=("Runs the CLI entry point.", True)):
                flows = build_flows(analysis)

            self.assertTrue(flows)
            self.assertTrue(flows[0].ai_summary_available)
            self.assertEqual(flows[0].summary, "Runs the CLI entry point.")

    def test_candidate_flow_keeps_deterministic_summary_when_ai_unavailable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            (root / "src").mkdir(parents=True)
            (root / "src/index.ts").write_text("export function parseThing() { return true }\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="library", url="demo://library", name="library", local_path=str(root)))
            with patch("backend.app.flow_engine.summarize_flow", return_value=("AI summary unavailable.", False)):
                flows = build_flows(analysis)

            self.assertTrue(flows)
            self.assertFalse(flows[0].ai_summary_available)
            self.assertIn("Low-confidence behavior candidate", flows[0].summary)

    def test_ai_summary_cleanup_discards_chatty_preamble(self):
        text = """Here is the translation of the code flow into a single business-language sentence:

The booking process notifies the provider after a booking is created.

This sentence captures the core idea."""

        self.assertEqual(_clean_ai_summary(text), "The booking process notifies the provider after a booking is created.")

    def test_unavailable_ollama_cache_does_not_block_later_enabled_flow_engine_mock(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "cli-cache"
            (root / "bin").mkdir(parents=True)
            (root / "bin/tool.py").write_text("def main():\n    return True\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="cli-cache", url="demo://cli-cache", name="cli-cache", local_path=str(root)))
            with patch("backend.app.flow_engine.summarize_flow", return_value=("Runs command input.", True)):
                flow = build_flows(analysis)[0]

            self.assertTrue(flow.ai_summary_available)
            self.assertEqual(flow.summary, "Runs command input.")

    def test_missing_local_import_is_reported_as_unknown_region(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "missing-import"
            (root / "src").mkdir(parents=True)
            (root / "src/app.ts").write_text("import { missing } from './missing';\nexport function run() { return missing(); }\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="missing-import", url="demo://missing", name="missing", local_path=str(root)))
            diagnostics = build_diagnostics(analysis, 0, False)

            self.assertIn("src/app.ts -> ./missing", diagnostics.unknowns.missingDependencies)
            self.assertGreaterEqual(diagnostics.coverage.unknownRegions, 1)

    def test_directory_index_import_resolves_without_missing_dependency(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "directory-import"
            (root / "src/services").mkdir(parents=True)
            (root / "src/app.ts").write_text("import { createBooking } from './services';\nexport function run() { return createBooking(); }\n", encoding="utf-8")
            (root / "src/services/index.ts").write_text("export function createBooking() { return true; }\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="directory-import", url="demo://directory", name="directory", local_path=str(root)))
            diagnostics = build_diagnostics(analysis, 0, False)
            import_edges = {(edge.source, edge.target) for edge in analysis.structure.edges if edge.kind == "imports"}

            self.assertIn(("file:src/app.ts", "file:src/services/index.ts"), import_edges)
            self.assertNotIn("src/app.ts -> ./services", diagnostics.unknowns.missingDependencies)

    def test_flow_expansion_reuses_directory_index_import_resolution(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "flow-directory-import"
            (root / "src/services").mkdir(parents=True)
            (root / "package.json").write_text('{"dependencies":{"express":"latest"}}\n', encoding="utf-8")
            (root / "src/app.ts").write_text(
                "import express from 'express';\n"
                "import { createBooking } from './services';\n"
                "const app = express();\n"
                "app.post('/booking', async (req, res) => {\n"
                "  const booking = await createBooking(req.body);\n"
                "  res.json(booking);\n"
                "});\n",
                encoding="utf-8",
            )
            (root / "src/services/index.ts").write_text(
                "import { saveBooking } from '../booking.repository';\n"
                "export async function createBooking(input: any) {\n"
                "  return saveBooking(input);\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "src/booking.repository.ts").write_text("export async function saveBooking(input: any) {\n  return { id: 'booking_1', ...input };\n}\n", encoding="utf-8")

            analysis = analyze_repo(Repo(id="flow-directory-import", url="demo://flow-directory", name="flow-directory", local_path=str(root)))
            booking_flow = next(flow for flow in build_flows(analysis) if flow.name == "Booking Flow")

            self.assertIn("src/services/index.ts", booking_flow.source_files)
            self.assertIn("src/booking.repository.ts", booking_flow.source_files)

    def test_risks_are_ranked_with_evidence_metadata(self):
        repo = create_demo_repo()
        analysis = analyze_repo(repo)
        risks = find_risks(analysis)

        self.assertTrue(risks)
        self.assertEqual([risk.rank for risk in risks], list(range(1, len(risks) + 1)))
        self.assertTrue(all(risk.evidence_count > 0 for risk in risks))
        self.assertTrue(all(risk.source_files for risk in risks))
        self.assertTrue(all(risk.source_locations for risk in risks))

    def test_frontend_filter_empty_state_uses_scan_state_not_undefined_result(self):
        source = Path("src/main.tsx").read_text(encoding="utf-8")

        self.assertNotIn("Boolean(result)", source)
        self.assertIn("No flows match the current filters.", source)

    def test_clone_falls_back_to_github_archive_when_git_fails(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("sample-main/README.md", "# Sample\n")
            archive.writestr("sample-main/src/index.ts", "export function run() { return true }\n")
        archive_payload = archive_bytes.getvalue()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return archive_payload

        with TemporaryDirectory() as tmp:
            with patch("backend.app.scanner.REPOS_DIR", Path(tmp)), patch("backend.app.scanner._run_git", side_effect=subprocess.CalledProcessError(1, ["git"], stderr="early EOF")), patch("backend.app.scanner.urllib.request.urlopen", return_value=FakeResponse()):
                repo = clone_public_repo("https://github.com/example/sample")

            self.assertTrue((Path(repo.local_path) / "README.md").exists())
            self.assertTrue((Path(repo.local_path) / "src/index.ts").exists())

    def test_archive_fallback_rejects_paths_outside_destination(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("sample-main/README.md", "# Sample\n")
            archive.writestr("../escaped.txt", "escape\n")
        archive_payload = archive_bytes.getvalue()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return archive_payload

        with TemporaryDirectory() as tmp:
            with patch("backend.app.scanner.REPOS_DIR", Path(tmp)), patch("backend.app.scanner._run_git", side_effect=subprocess.CalledProcessError(1, ["git"], stderr="early EOF")), patch("backend.app.scanner.urllib.request.urlopen", return_value=FakeResponse()):
                with self.assertRaisesRegex(ValueError, "unsafe paths"):
                    clone_public_repo("https://github.com/example/sample")
            self.assertFalse((Path(tmp) / "escaped.txt").exists())

    def test_sparse_checkout_includes_repo_named_package_directory(self):
        paths = _sparse_paths("Scrapling")

        self.assertIn("/scrapling/**", paths)

    def test_sparse_checkout_includes_odoo_addons(self):
        paths = _sparse_paths("odoo")

        self.assertIn("/addons/**", paths)

    def test_frontend_has_six_curated_live_demo_repos(self):
        source = Path("src/main.tsx").read_text(encoding="utf-8")
        urls = [
            "https://github.com/medusajs/medusa",
            "https://github.com/al1abb/invoify",
            "https://github.com/pravee42/next-js-pos-invoice-application",
            "https://github.com/vladimir-siedykh/booking-calendar",
            "https://github.com/PubliciaLLC/go-help-desk",
            "https://github.com/guranshdeol/Invoice-Generator",
        ]

        self.assertIn("DEFAULT_REPO_URL = MEDUSA_REPO_URL", source)
        self.assertIn("useState(DEFAULT_REPO_URL)", source)
        for url in urls:
            self.assertEqual(source.count(url), 1, url)
        self.assertIn("POPULAR_REPOS.map", source)
        self.assertIn("<select className=\"repo-picker\"", source)
        self.assertIn("onChange={(event) => setRepoUrl(event.target.value)}", source)
        self.assertNotIn("onClick={() => void startScan(\"scan\", repo.url)}", source)

    def test_frontend_shows_centered_scan_progress_state(self):
        source = Path("src/main.tsx").read_text(encoding="utf-8")

        self.assertIn('scan?.status === "queued" || scan?.status === "running"', source)
        self.assertIn("ScanProgressPanel", source)
        self.assertIn("Scan in progress", source)

    def test_old_synthetic_demo_branding_is_absent_from_public_source(self):
        checked_paths = [
            Path("src/main.tsx"),
            Path("backend/app/scanner.py"),
            Path("README.md"),
            Path("backend/README.md"),
        ]
        old_demo_brand = "urban" + "seva"

        for path in checked_paths:
            source = path.read_text(encoding="utf-8").lower()
            self.assertNotIn(old_demo_brand, source, str(path))

    def test_load_scan_does_not_create_directory_for_missing_scan(self):
        with TemporaryDirectory() as tmp:
            with patch("backend.app.storage.SCANS_DIR", Path(tmp) / "scans"):
                self.assertIsNone(load_scan("missing-scan"))
                self.assertFalse((Path(tmp) / "scans" / "missing-scan").exists())

    def test_create_scan_rejects_when_capacity_is_full(self):
        self.assertTrue(hasattr(api, "SCAN_CAPACITY"))
        acquired = []
        while api.SCAN_CAPACITY.acquire(blocking=False):
            acquired.append(True)
        try:
            with self.assertRaises(HTTPException) as context:
                api.create_scan(ScanRequest(repoUrl="https://github.com/example/sample"))
            self.assertEqual(context.exception.status_code, 429)
        finally:
            for _ in acquired:
                api.SCAN_CAPACITY.release()


if __name__ == "__main__":
    unittest.main()
