import unittest
import uuid
from pathlib import Path
import shutil

from HiveStateManager import HiveStateManager


class HiveStateManagerDiskSyncTests(unittest.TestCase):
    def _make_repo_root(self):
        root = Path(__file__).resolve().parent / f"_tmp_state_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_get_effective_file_text_refreshes_stale_cached_content(self):
        repo_root = self._make_repo_root()
        target = repo_root / "sample.py"
        target.write_text("print('disk')\n", encoding="utf-8")

        state = HiveStateManager(
            snapshot_path=repo_root / "snapshot.json",
            repo_root=repo_root,
        )
        state.set_file_text("sample.py", "print('cached')\n", source="applied_patch")

        content = state.get_effective_file_text("sample.py")

        self.assertEqual(content, "print('disk')\n")
        self.assertEqual(state.get_file_text("sample.py"), "print('disk')\n")
        self.assertEqual(state.get_file_state("sample.py")["source"], "disk")

    def test_load_snapshot_reconciles_tracked_files_with_disk(self):
        repo_root = self._make_repo_root()
        target = repo_root / "sample.py"
        target.write_text("print('before')\n", encoding="utf-8")
        snapshot_path = repo_root / "snapshot.json"

        state = HiveStateManager(
            snapshot_path=snapshot_path,
            repo_root=repo_root,
        )
        state.set_file_text("sample.py", "print('before')\n", source="applied_patch")
        state.save_snapshot()

        target.write_text("print('after')\n", encoding="utf-8")

        reloaded = HiveStateManager(
            snapshot_path=snapshot_path,
            repo_root=repo_root,
        )
        loaded = reloaded.load_snapshot()

        self.assertTrue(loaded)
        self.assertEqual(reloaded.get_file_text("sample.py"), "print('after')\n")
        self.assertEqual(reloaded.get_file_state("sample.py")["source"], "disk")


if __name__ == "__main__":
    unittest.main()
