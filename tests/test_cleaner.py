"""cleaner.py 테스트"""

import os
import shlex
import tempfile
import unittest

from app.cleaner import delete_path


class TestDeleteNormal(unittest.TestCase):
    def test_delete_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
            f.write(b"test")
        ok, code, msg = delete_path(path)
        self.assertTrue(ok)
        self.assertEqual(code, "ok")
        self.assertFalse(os.path.exists(path))

    def test_delete_directory(self):
        td = tempfile.mkdtemp()
        # 하위 파일 생성
        with open(os.path.join(td, "file.txt"), "w") as f:
            f.write("test")
        ok, code, msg = delete_path(td)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(td))

    def test_delete_directory_with_recreate(self):
        td = tempfile.mkdtemp()
        ok, code, msg = delete_path(td, recreate=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.isdir(td))  # 재생성됨
        os.rmdir(td)

    def test_delete_nonexistent_is_noop(self):
        ok, code, msg = delete_path("/nonexistent/path/xyz")
        # 존재하지 않는 경로는 isdir/isfile 모두 False → 아무것도 안 함
        self.assertTrue(ok)

    def test_permission_denied_returns_error(self):
        # /System은 SIP로 보호됨
        ok, code, msg = delete_path("/System")
        self.assertFalse(ok)


class TestShellEscaping(unittest.TestCase):
    """shlex.quote가 올바르게 적용되는지 확인"""

    def test_single_quote_escaped(self):
        path = "/tmp/test'injection"
        escaped = shlex.quote(path)
        # shlex.quote가 싱글 쿼트를 안전하게 처리
        self.assertNotEqual(escaped, f"'{path}'")  # 원본 그대로면 위험

    def test_semicolon_escaped(self):
        path = "/tmp/test;rm -rf /"
        escaped = shlex.quote(path)
        # 세미콜론이 쉘에서 실행되지 않도록 쿼팅됨
        self.assertIn("'", escaped)

    def test_safe_path_quoted(self):
        path = "/Users/test/Library/Caches"
        escaped = shlex.quote(path)
        # shlex.quote 결과를 eval하면 원래 경로가 나와야 함
        self.assertIn(path, escaped)


if __name__ == "__main__":
    unittest.main()
