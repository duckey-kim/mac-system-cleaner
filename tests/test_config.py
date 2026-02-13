"""config.py 테스트"""

import unittest
from pathlib import Path

from app.config import (
    HOME, LEARNED_PATH, KNOWN_FOLDERS,
    get_folder_info, is_path_allowed, reload_folders,
)


class TestConstants(unittest.TestCase):
    def test_home_is_real_path(self):
        self.assertEqual(HOME, str(Path.home()))

    def test_learned_path_exists(self):
        self.assertTrue(LEARNED_PATH.endswith("learned_folders.json"))


class TestGetFolderInfo(unittest.TestCase):
    def test_known_folder_returns_desc_and_risk(self):
        desc, risk = get_folder_info("caches")
        self.assertIn("캐시", desc)
        self.assertIn(risk, ("safe", "moderate", "caution", "unknown"))

    def test_case_insensitive(self):
        desc1, _ = get_folder_info("Caches")
        desc2, _ = get_folder_info("caches")
        self.assertEqual(desc1, desc2)

    def test_unknown_folder_returns_empty(self):
        desc, risk = get_folder_info("completely_unknown_folder_xyz")
        self.assertEqual(desc, "")
        self.assertEqual(risk, "unknown")


class TestIsPathAllowed(unittest.TestCase):
    def test_home_allowed(self):
        self.assertTrue(is_path_allowed(HOME))
        self.assertTrue(is_path_allowed(HOME + "/Library/Caches"))

    def test_var_log_allowed(self):
        self.assertTrue(is_path_allowed("/var/log"))
        self.assertTrue(is_path_allowed("/var/log/system.log"))

    def test_var_spool_blocked(self):
        self.assertFalse(is_path_allowed("/var/spool"))

    def test_etc_blocked(self):
        self.assertFalse(is_path_allowed("/etc/passwd"))

    def test_root_blocked(self):
        self.assertFalse(is_path_allowed("/"))

    def test_empty_blocked(self):
        self.assertFalse(is_path_allowed(""))


class TestReloadFolders(unittest.TestCase):
    def test_reload_preserves_known_folders(self):
        before = len(KNOWN_FOLDERS)
        reload_folders()
        after = len(KNOWN_FOLDERS)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
