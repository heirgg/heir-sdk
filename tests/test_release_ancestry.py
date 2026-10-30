"""Exercise the release ancestry gate against real, isolated Git histories."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseAncestryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "checkout"
        self.remote = Path(self.directory.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "--initial-branch=main", str(self.root)], check=True)
        self.git("config", "user.name", "SDK release tests")
        self.git("config", "user.email", "sdk@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("remote", "add", "origin", str(self.remote))
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/release.py", self.root / "scripts/release.py")
        (self.root / "typescript/src").mkdir(parents=True)
        (self.root / "typescript/package.json").write_text('{"version":"0.1.0"}')
        (self.root / "typescript/src/version.ts").write_text('export const VERSION = "0.1.0";')
        self.commit("base")

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *arguments], text=True, stderr=subprocess.PIPE
        ).strip()

    def commit(self, contents):
        (self.root / "fixture.txt").write_text(contents)
        self.git("add", ".")
        self.git("commit", "-qm", contents)
        return self.git("rev-parse", "HEAD")

    def fetch_main(self):
        # Publish only into this test's local bare repository, then fetch the same
        # remote-tracking ref that the release checkout supplies in Actions.
        self.git("push", "-q", "origin", "refs/heads/main:refs/heads/main")
        self.git("fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")

    def test_accepts_detached_tag_at_main_tip(self):
        self.git("tag", "typescript/v0.1.0")
        self.fetch_main()
        self.git("checkout", "-q", "--detach", "refs/tags/typescript/v0.1.0")
        release.require_main("typescript/v0.1.0", self.root)

    def test_accepts_annotated_tag_on_earlier_main_commit(self):
        self.git("tag", "-a", "python/v0.1.0", "-m", "release")
        self.commit("later main change")
        self.fetch_main()
        self.git("checkout", "-q", "--detach", "refs/tags/python/v0.1.0")
        release.require_main("python/v0.1.0", self.root)

    def test_rejects_release_tag_on_unmerged_branch(self):
        self.git("checkout", "-qb", "unreviewed")
        self.commit("unmerged feature")
        self.git("tag", "go/v0.1.0")
        self.fetch_main()
        self.git("checkout", "-q", "--detach", "refs/tags/go/v0.1.0")
        with self.assertRaisesRegex(ValueError, "not an ancestor"):
            release.require_main("go/v0.1.0", self.root)

    def test_rejects_head_that_differs_from_tag_even_when_both_are_on_main(self):
        self.git("tag", "typescript/v0.1.0")
        self.commit("another main commit")
        self.fetch_main()
        with self.assertRaisesRegex(ValueError, "HEAD does not match"):
            release.require_main("typescript/v0.1.0", self.root)

    def test_rejects_missing_remote_main(self):
        self.git("tag", "typescript/v0.1.0")
        with self.assertRaisesRegex(ValueError, "Fetch origin/main"):
            release.require_main("typescript/v0.1.0", self.root)

    def test_rejects_missing_tag(self):
        self.fetch_main()
        with self.assertRaisesRegex(ValueError, "release tag"):
            release.require_main("typescript/v0.1.0", self.root)

    def test_rejects_tag_that_does_not_resolve_to_a_commit(self):
        self.git("tag", "typescript/v0.1.0", self.git("rev-parse", "HEAD^{tree}"))
        self.fetch_main()
        with self.assertRaisesRegex(ValueError, "release tag"):
            release.require_main("typescript/v0.1.0", self.root)

    def test_cli_flag_enforces_ancestry(self):
        self.git("checkout", "-qb", "unreviewed")
        self.commit("unmerged release")
        self.git("tag", "typescript/v0.1.0")
        self.fetch_main()
        self.git("checkout", "-q", "--detach", "refs/tags/typescript/v0.1.0")
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts/release.py"), "typescript", "typescript/v0.1.0", "--require-main"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not an ancestor", result.stderr)


if __name__ == "__main__":
    unittest.main()
