import unittest
from pathlib import Path

from helpers import git, make_repo, run_cli


class FetchSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo, self.commit = make_repo({
            "src/main.c": "int main(void) { return 0; }\n",
            "data/app.desktop": "[Desktop Entry]\nName=App\n",
        })
        self.root = Path(self.tmp.name) / "sources"
        self.url = f"file://{self.repo}"

    def tearDown(self):
        self.tmp.cleanup()

    def test_clones_and_prints_commit(self):
        code, out, err = run_cli("fetch-source", "app", self.url, "--root", self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["commit"], self.commit)
        self.assertEqual(out["id"], "app")
        self.assertFalse(out["reused"])
        self.assertTrue((self.root / "app" / "src" / "main.c").exists())

    def test_clone_is_shallow_and_blobless(self):
        run_cli("fetch-source", "app", self.url, "--root", self.root, check=True)
        clone = self.root / "app"
        self.assertEqual(git(clone, "rev-parse", "--is-shallow-repository"), "true")
        self.assertEqual(git(clone, "config", "remote.origin.partialclonefilter"), "blob:none")

    def test_reuses_existing_clone(self):
        run_cli("fetch-source", "app", self.url, "--root", self.root, check=True)
        code, out, err = run_cli("fetch-source", "app", self.url, "--root", self.root)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["reused"])
        self.assertEqual(out["commit"], self.commit)

    def test_ref_by_commit_hash(self):
        first = self.commit
        (self.repo / "src" / "main.c").write_text("int main(void) { return 1; }\n")
        git(self.repo, "commit", "-q", "-am", "second")
        code, out, err = run_cli("fetch-source", "app", self.url, "--ref", first, "--root", self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["commit"], first)

    def test_ref_by_tag(self):
        git(self.repo, "tag", "v1.0")
        (self.repo / "src" / "main.c").write_text("int main(void) { return 1; }\n")
        git(self.repo, "commit", "-q", "-am", "second")
        code, out, err = run_cli("fetch-source", "app", self.url, "--ref", "v1.0", "--root", self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["commit"], self.commit)

    def test_existing_clone_moves_to_new_ref(self):
        run_cli("fetch-source", "app", self.url, "--root", self.root, check=True)
        (self.repo / "src" / "main.c").write_text("int main(void) { return 1; }\n")
        git(self.repo, "commit", "-q", "-am", "second")
        second = git(self.repo, "rev-parse", "HEAD")
        code, out, err = run_cli("fetch-source", "app", self.url, "--ref", second, "--root", self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["commit"], second)
        self.assertTrue(out["reused"])

    def test_refuses_clone_of_other_url(self):
        run_cli("fetch-source", "app", self.url, "--root", self.root, check=True)
        other_tmp, other_repo, _ = make_repo({"x": "y\n"})
        try:
            code, out, err = run_cli("fetch-source", "app", f"file://{other_repo}", "--root", self.root)
            self.assertNotEqual(code, 0)
            self.assertIn("different URL", out["error"])
        finally:
            other_tmp.cleanup()

    def test_sparse_paths(self):
        code, out, err = run_cli("fetch-source", "app", self.url, "--root", self.root, "--path", "src")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / "app" / "src" / "main.c").exists())
        self.assertFalse((self.root / "app" / "data" / "app.desktop").exists())

    def test_bad_id_rejected(self):
        code, out, err = run_cli("fetch-source", "../escape", self.url, "--root", self.root)
        self.assertNotEqual(code, 0)
        self.assertIn("id", out["error"])

    def test_help(self):
        code, _, _ = run_cli("fetch-source", "--help")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
