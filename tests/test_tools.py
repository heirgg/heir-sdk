"""Release/spec tooling guardrails, using temporary repositories and fixtures."""
import importlib.util
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("sync-spec")
contracts = load("check-contracts")
release = load("release")
published = load("check-published")


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / "spec", self.root / "spec")
        (self.root / "tests").mkdir()
        shutil.copyfile(ROOT / "tests/contracts.json", self.root / "tests/contracts.json")
        (self.root / "typescript/src").mkdir(parents=True)
        (self.root / "typescript/package.json").write_text('{"version":"0.1.0"}')
        (self.root / "typescript/src/version.ts").write_text('export const VERSION = "0.1.0";')
        (self.root / "python/src/heir").mkdir(parents=True)
        (self.root / "python/pyproject.toml").write_text('version = "0.1.0"')
        (self.root / "python/src/heir/_version.py").write_text('__version__ = "0.1.0"')
        (self.root / "go").mkdir()
        (self.root / "go/version.go").write_text('const Version = "0.1.0"')

    def test_snapshot_hash_detects_changed_document(self):
        path = self.root / "spec/public-openapi.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "differs"):
            sync.check_snapshot(self.root)

    def test_accidental_backend_filename_is_rejected(self):
        (self.root / "spec/openapi.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            sync.check_snapshot(self.root)

    def test_ignored_source_documents_are_never_declared_committed(self):
        repository = self.root / "backend"
        source = repository / "ignored"
        source.mkdir(parents=True)
        (repository / ".gitignore").write_text("ignored/\n")
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        subprocess.run(["git", "-C", str(repository), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(repository), "-c", "user.name=SDK tests", "-c", "user.email=sdk@example.invalid",
                        "commit", "-qm", "fixture"], check=True)
        for original in sync.DOCUMENTS:
            (source / original).write_text('{"paths":{},"components":{}}')
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            sync.synchronize(source, root=self.root)
        sync.synchronize(source, allow_dirty=True, root=self.root)
        self.assertTrue(sync.check_snapshot(self.root)["uncommittedSource"])

    def test_all_operations_are_required(self):
        path = self.root / "tests/contracts.json"
        document = json.loads(path.read_text())
        document["cases"].pop()
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "coverage"):
            contracts.check(self.root)

    def test_wrong_method_is_rejected(self):
        path = self.root / "tests/contracts.json"
        document = json.loads(path.read_text())
        document["cases"][0]["method"] = "DELETE"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "route mismatch"):
            contracts.check(self.root)

    def test_current_release_versions(self):
        for package in ("typescript", "python", "go"):
            self.assertEqual(release.validate(package, f"{package}/v0.1.0", self.root)["channel"], "latest")

    def test_tag_mismatch(self):
        with self.assertRaisesRegex(ValueError, "must agree"):
            release.validate("typescript", "typescript/v0.2.0", self.root)

    def test_invalid_tag(self):
        for value in ("typescript/v1.0.0;echo", "v0.1.0", "typescript/v01.0.0", "typescript/v0.2.0-01", "typescript/v0.2.0-beta.01"):
            with self.assertRaises(ValueError):
                release.validate("typescript", value)

    def test_prerelease_uses_next(self):
        (self.root / "typescript/package.json").write_text('{"version":"0.2.0-beta.1"}')
        (self.root / "typescript/src/version.ts").write_text('export const VERSION = "0.2.0-beta.1";')
        self.assertEqual(release.validate("typescript", "typescript/v0.2.0-beta.1", self.root)["channel"], "next")

    def test_exact_npm_artifact_skips_publishing(self):
        (self.root / "sdk.tgz").write_bytes(b"validated")
        record = {"dist": {"integrity": "sha512-" + base64.b64encode(hashlib.sha512(b"validated").digest()).decode()}}
        with patch.object(published.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            self.assertFalse(published.check("typescript", "0.1.0", self.root))

    def test_npm_version_collision_is_not_ignored(self):
        (self.root / "sdk.tgz").write_bytes(b"validated")
        with patch.object(published.urllib.request, "urlopen", return_value=io.BytesIO(b'{"dist":{"integrity":"different"}}')):
            with self.assertRaisesRegex(ValueError, "different bytes"):
                published.check("typescript", "0.1.0", self.root)

    def test_registry_404_allows_first_publish(self):
        (self.root / "sdk.tgz").write_bytes(b"validated")
        error = urllib.error.HTTPError("https://registry.npmjs.org", 404, "not found", {}, None)
        with patch.object(published.urllib.request, "urlopen", side_effect=error):
            self.assertTrue(published.check("typescript", "0.1.0", self.root))

    def test_registry_failure_is_not_treated_as_missing(self):
        (self.root / "sdk.tgz").write_bytes(b"validated")
        error = urllib.error.HTTPError("https://registry.npmjs.org", 503, "unavailable", {}, None)
        with patch.object(published.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                published.check("typescript", "0.1.0", self.root)

    def test_partial_pypi_upload_can_resume(self):
        (self.root / "sdk.whl").write_bytes(b"wheel")
        (self.root / "sdk.tar.gz").write_bytes(b"sdist")
        record = {"urls": [{"filename": "sdk.whl", "digests": {"sha256": hashlib.sha256(b"wheel").hexdigest()}}]}
        with patch.object(published.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            self.assertTrue(published.check("python", "0.1.0", self.root))

    def test_pypi_version_collision_is_not_ignored(self):
        (self.root / "sdk.whl").write_bytes(b"wheel")
        record = {"urls": [{"filename": "sdk.whl", "digests": {"sha256": "different"}}]}
        with patch.object(published.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(record).encode())):
            with self.assertRaisesRegex(ValueError, "different bytes"):
                published.check("python", "0.1.0", self.root)


if __name__ == "__main__":
    unittest.main()
