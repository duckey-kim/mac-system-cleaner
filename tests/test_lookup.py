"""lookup.py 테스트"""

import json
import os
import tempfile
import threading
import unittest

from app.lookup import (
    pattern_match, _load_json, _save_json, _file_lock,
    BUNDLE_PREFIXES, KEYWORD_PATTERNS,
)


class TestPatternMatch(unittest.TestCase):
    def test_apple_bundle(self):
        desc, risk = pattern_match("com.apple.Safari")
        self.assertIn("Apple", desc)
        self.assertEqual(risk, "moderate")

    def test_google_bundle(self):
        desc, risk = pattern_match("com.google.Chrome")
        self.assertIn("Google", desc)

    def test_microsoft_bundle(self):
        desc, risk = pattern_match("com.microsoft.Word")
        self.assertIn("Microsoft", desc)

    def test_cache_keyword(self):
        desc, risk = pattern_match("SomeAppCache")
        self.assertIn("캐시", desc)
        self.assertEqual(risk, "safe")

    def test_log_keyword(self):
        desc, risk = pattern_match("logs")
        self.assertIn("로그", desc)

    def test_node_modules(self):
        desc, risk = pattern_match("node_modules")
        self.assertIn("Node.js", desc)
        self.assertEqual(risk, "safe")

    def test_path_based_caches(self):
        desc, risk = pattern_match("SomeUnknown", "/Users/me/Library/Caches/SomeUnknown")
        self.assertIn("캐시", desc)
        self.assertEqual(risk, "safe")

    def test_path_based_containers(self):
        desc, risk = pattern_match("SomeApp", "/Users/me/Library/Containers/SomeApp")
        self.assertIn("샌드박스", desc)

    def test_unknown_returns_none(self):
        desc, risk = pattern_match("completely_random_xyz_123")
        self.assertIsNone(desc)
        self.assertIsNone(risk)


class TestBundlePrefixes(unittest.TestCase):
    def test_all_prefixes_have_tuple(self):
        for prefix, (desc, risk) in BUNDLE_PREFIXES.items():
            self.assertIsInstance(desc, str)
            self.assertIn(risk, ("safe", "moderate", "caution"))

    def test_prefix_starts_with_dot_notation(self):
        for prefix in BUNDLE_PREFIXES:
            self.assertIn(".", prefix)


class TestKeywordPatterns(unittest.TestCase):
    def test_all_patterns_are_valid_regex(self):
        import re
        for pattern, desc, risk in KEYWORD_PATTERNS:
            re.compile(pattern)  # ValueError if invalid

    def test_all_risks_valid(self):
        for _, _, risk in KEYWORD_PATTERNS:
            self.assertIn(risk, ("safe", "moderate", "caution"))


class TestJsonIO(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        data = {"test_key": {"desc": "테스트", "risk": "safe", "source": "test"}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            _save_json(path, data)
            loaded = _load_json(path)
            self.assertEqual(loaded, data)
        finally:
            os.unlink(path)

    def test_compact_format(self):
        data = {"a": {"x": 1}, "b": {"y": 2}}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            _save_json(path, data)
            with open(path) as f:
                lines = f.readlines()
            # 첫줄 {, 마지막줄 }, 중간은 항목별 한 줄
            self.assertEqual(lines[0].strip(), "{")
            self.assertTrue(lines[-1].strip().startswith("}"))
            self.assertEqual(len(lines), 4)  # { + 2 items + }
        finally:
            os.unlink(path)

    def test_load_nonexistent_returns_empty(self):
        result = _load_json("/nonexistent/path/xyz.json")
        self.assertEqual(result, {})

    def test_concurrent_write_no_data_loss(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            # 초기 데이터
            initial = {f"key_{i}": {"v": i} for i in range(20)}
            _save_json(path, initial)

            errors = []

            def write_entry(idx):
                try:
                    with _file_lock:
                        d = _load_json(path)
                        d[f"thread_{idx}"] = {"v": idx}
                        _save_json(path, d)
                except Exception as e:
                    errors.append(str(e))

            threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            final = _load_json(path)
            self.assertEqual(len(errors), 0)
            # 초기 20 + 스레드 10 = 30
            self.assertEqual(len(final), 30)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
