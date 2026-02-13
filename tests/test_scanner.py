"""scanner.py 테스트"""

import unittest

from app.scanner import (
    format_size, _parse_du, _make_item, get_disk_info,
    MIN_GROUP_MB, MIN_ITEM_MB, MIN_CHILD_BYTES, MAX_ITEMS_PER_GROUP, MAX_CHILDREN,
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


if __name__ == "__main__":
    unittest.main()
