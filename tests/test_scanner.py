"""scanner.py 테스트"""

import unittest
from unittest.mock import patch, MagicMock

from app.scanner import (
    format_size, _parse_du, _make_item, get_disk_info,
    _get_dir_total, _scan_library, _scan_simple_dir, _scan_dev_caches,
    scan_system,
    MIN_GROUP_MB, MIN_ITEM_MB, MIN_CHILD_BYTES, MAX_ITEMS_PER_GROUP, MAX_CHILDREN,
    CATEGORY_META, CATEGORY_ORDER, DEV_CACHE_PATHS,
    MIN_DEV_CACHE_MB, MIN_DOWNLOAD_MB, MIN_TRASH_MB, MIN_MEDIA_MB, MIN_LOG_MB,
)


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(500), "500 B")

    def test_kilobytes(self):
        self.assertEqual(format_size(1536), "1.5 KB")

    def test_megabytes(self):
        self.assertEqual(format_size(10 * 1024 * 1024), "10.0 MB")

    def test_gigabytes(self):
        self.assertEqual(format_size(2 * 1024**3), "2.00 GB")

    def test_zero(self):
        self.assertEqual(format_size(0), "0 B")


class TestParseDu(unittest.TestCase):
    def test_basic_parsing(self):
        output = "1024\t/foo/bar\n2048\t/foo/baz\n3072\t/foo\n"
        result = _parse_du(output, "/foo")
        self.assertEqual(result["/foo/bar"], 1024 * 1024)
        self.assertEqual(result["/foo/baz"], 2048 * 1024)
        self.assertNotIn("/foo", result)  # base_path 제외

    def test_empty_output(self):
        result = _parse_du("", "/foo")
        self.assertEqual(result, {})

    def test_malformed_lines_skipped(self):
        output = "not_a_number\t/foo/bar\n1024\t/foo/baz\n"
        result = _parse_du(output, "/foo")
        self.assertNotIn("/foo/bar", result)
        self.assertIn("/foo/baz", result)

    def test_single_column_skipped(self):
        output = "1024\n2048\t/foo/bar\n"
        result = _parse_du(output, "/foo")
        self.assertEqual(len(result), 1)


class TestMakeItem(unittest.TestCase):
    def test_nonexistent_path_treated_as_file(self):
        result = _make_item("/nonexistent/path/xyz", "xyz", 1000)
        # 존재하지 않는 경로: islink=False, isdir=False → 파일 항목으로 반환
        self.assertIsNotNone(result)
        self.assertFalse(result["is_dir"])

    def test_existing_directory(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            result = _make_item(td, os.path.basename(td), 5000)
            self.assertIsNotNone(result)
            self.assertTrue(result["is_dir"])
            self.assertEqual(result["size"], 5000)
            self.assertIn("risk", result)

    def test_symlink_returns_none(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            link = os.path.join(td, "link")
            os.symlink(td, link)
            result = _make_item(link, "link", 1000)
            self.assertIsNone(result)


class TestConstants(unittest.TestCase):
    def test_min_group_mb_positive(self):
        self.assertGreater(MIN_GROUP_MB, 0)

    def test_min_item_mb_less_than_group(self):
        self.assertLessEqual(MIN_ITEM_MB, MIN_GROUP_MB)

    def test_max_items_reasonable(self):
        self.assertGreater(MAX_ITEMS_PER_GROUP, 0)
        self.assertLessEqual(MAX_ITEMS_PER_GROUP, 100)

    def test_max_children_reasonable(self):
        self.assertGreater(MAX_CHILDREN, 0)
        self.assertLessEqual(MAX_CHILDREN, 100)


class TestGetDiskInfo(unittest.TestCase):
    def test_returns_expected_keys(self):
        info = get_disk_info()
        for key in ("total", "used", "available", "percent",
                     "total_bytes", "used_bytes", "free_bytes"):
            self.assertIn(key, info)

    def test_bytes_are_positive(self):
        info = get_disk_info()
        self.assertGreater(info["total_bytes"], 0)
        self.assertGreater(info["used_bytes"], 0)
        self.assertGreater(info["free_bytes"], 0)


class TestGetDirTotal(unittest.TestCase):
    def test_extracts_total_from_du_output(self):
        output = "1024\t/foo/bar\n2048\t/foo/baz\n5000\t/foo\n"
        self.assertEqual(_get_dir_total(output, "/foo"), 5000 * 1024)

    def test_returns_zero_when_not_found(self):
        output = "1024\t/foo/bar\n"
        self.assertEqual(_get_dir_total(output, "/foo"), 0)

    def test_handles_empty_output(self):
        self.assertEqual(_get_dir_total("", "/foo"), 0)

    def test_handles_malformed_line(self):
        output = "abc\t/foo\n"
        self.assertEqual(_get_dir_total(output, "/foo"), 0)


class TestScanLibrary(unittest.TestCase):
    @patch('app.scanner.subprocess.run')
    def test_returns_list(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = _scan_library()
        self.assertIsInstance(result, list)

    @patch('app.scanner.subprocess.run')
    def test_du_failure_returns_empty(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        result = _scan_library()
        self.assertEqual(result, [])

    @patch('app.scanner.subprocess.run')
    def test_groups_have_expected_keys(self, mock_run):
        # 큰 du 출력을 시뮬레이션
        import os
        from app.config import HOME
        lib = os.path.join(HOME, "Library")
        caches = os.path.join(lib, "Caches")
        sub = os.path.join(caches, "Google")
        output = f"60000\t{caches}\n25000\t{sub}\n100000\t{lib}\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=output)
        result = _scan_library()
        if result:
            g = result[0]
            self.assertIn("label", g)
            self.assertIn("path", g)
            self.assertIn("items", g)
            self.assertIn("total_size", g)
            self.assertIn("total_size_formatted", g)


class TestScanSimpleDir(unittest.TestCase):
    def test_nonexistent_dir_returns_empty(self):
        result = _scan_simple_dir("/nonexistent_path_xyz", "test", 10)
        self.assertEqual(result, [])

    @patch('app.scanner.os.path.isdir', return_value=True)
    @patch('app.scanner.subprocess.run')
    def test_small_dir_filtered(self, mock_run, mock_isdir):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="100\t/test\n"  # 100KB < 10MB
        )
        result = _scan_simple_dir("/test", "test", 10)
        self.assertEqual(result, [])

    @patch('app.scanner.os.path.isdir', return_value=True)
    @patch('app.scanner.subprocess.run')
    def test_du_error_returns_empty(self, mock_run, mock_isdir):
        mock_run.return_value = MagicMock(returncode=2, stdout="")
        result = _scan_simple_dir("/test", "test", 10)
        self.assertEqual(result, [])

    @patch('app.scanner.os.path.isdir', return_value=True)
    @patch('app.scanner.subprocess.run')
    def test_du_exception_returns_empty(self, mock_run, mock_isdir):
        mock_run.side_effect = Exception("timeout")
        result = _scan_simple_dir("/test", "test", 10)
        self.assertEqual(result, [])


class TestScanDevCaches(unittest.TestCase):
    @patch('app.scanner.os.path.isdir', return_value=False)
    def test_skips_nonexistent_paths(self, mock_isdir):
        result = _scan_dev_caches()
        self.assertEqual(result, [])


class TestCategoryConstants(unittest.TestCase):
    def test_all_order_in_meta(self):
        for cat_id in CATEGORY_ORDER:
            self.assertIn(cat_id, CATEGORY_META)

    def test_meta_has_string_values(self):
        for cat_id, name in CATEGORY_META.items():
            self.assertIsInstance(name, str)
            self.assertTrue(len(name) > 0)

    def test_dev_cache_paths_format(self):
        for rel_path, desc in DEV_CACHE_PATHS:
            self.assertIsInstance(rel_path, str)
            self.assertIsInstance(desc, str)
            self.assertTrue(rel_path.startswith("."))

    def test_category_thresholds_positive(self):
        for val in [MIN_DEV_CACHE_MB, MIN_DOWNLOAD_MB, MIN_TRASH_MB, MIN_MEDIA_MB, MIN_LOG_MB]:
            self.assertGreater(val, 0)


class TestScanSystemIntegration(unittest.TestCase):
    @patch('app.scanner._scan_library', return_value=[])
    @patch('app.scanner._scan_dev_caches', return_value=[])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_has_required_fields(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        for key in ("categories", "groups", "disk_info", "tm_snapshots",
                     "total_cleanable", "total_cleanable_formatted"):
            self.assertIn(key, result)

    @patch('app.scanner._scan_library', return_value=[])
    @patch('app.scanner._scan_dev_caches', return_value=[])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_categories_is_list(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        self.assertIsInstance(result["categories"], list)

    @patch('app.scanner._scan_library', return_value=[
        {"label": "Library/Caches", "path": "/x", "items": [{"size": 100}],
         "total_size": 100, "total_size_formatted": "100 B"}
    ])
    @patch('app.scanner._scan_dev_caches', return_value=[])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_groups_have_category_field(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        for g in result["groups"]:
            self.assertIn("category", g)
            self.assertIn(g["category"], CATEGORY_META)

    @patch('app.scanner._scan_library', return_value=[
        {"label": "Library/Caches", "path": "/x", "items": [{"size": 500}],
         "total_size": 500, "total_size_formatted": "500 B"}
    ])
    @patch('app.scanner._scan_dev_caches', return_value=[
        {"label": ".npm", "path": "/y", "items": [{"size": 300}],
         "total_size": 300, "total_size_formatted": "300 B"}
    ])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_total_cleanable_sums_all_groups(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        self.assertEqual(result["total_cleanable"], 800)

    @patch('app.scanner._scan_library', return_value=[
        {"label": "Library/Caches", "path": "/x", "items": [{"size": 100}],
         "total_size": 100, "total_size_formatted": "100 B"}
    ])
    @patch('app.scanner._scan_dev_caches', return_value=[])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_categories_only_include_nonempty(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        cat_ids = [c["id"] for c in result["categories"]]
        self.assertIn("app_data", cat_ids)
        # 빈 카테고리는 제외
        self.assertNotIn("downloads", cat_ids)
        self.assertNotIn("trash", cat_ids)

    @patch('app.scanner._scan_library', return_value=[])
    @patch('app.scanner._scan_dev_caches', return_value=[])
    @patch('app.scanner._scan_downloads', return_value=[])
    @patch('app.scanner._scan_trash', return_value=[])
    @patch('app.scanner._scan_media', return_value=[])
    @patch('app.scanner._scan_system_logs', return_value=[])
    @patch('app.scanner.subprocess.run')
    def test_category_order_preserved(self, mock_run, *scan_mocks):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = scan_system()
        cat_ids = [c["id"] for c in result["categories"]]
        # 반환된 카테고리 순서가 CATEGORY_ORDER를 따르는지
        filtered_order = [c for c in CATEGORY_ORDER if c in cat_ids]
        self.assertEqual(cat_ids, filtered_order)


if __name__ == "__main__":
    unittest.main()
