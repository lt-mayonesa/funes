import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from funes.files import parse_gnome_copied_files, parse_uri_list, uri_to_filename


class ParseUriListTests(unittest.TestCase):
    def test_crlf_separated(self) -> None:
        data = b"file:///tmp/a.txt\r\nfile:///tmp/b.txt\r\n"
        self.assertEqual(parse_uri_list(data), ["file:///tmp/a.txt", "file:///tmp/b.txt"])

    def test_bare_lf_also_accepted(self) -> None:
        data = b"file:///tmp/a.txt\nfile:///tmp/b.txt\n"
        self.assertEqual(parse_uri_list(data), ["file:///tmp/a.txt", "file:///tmp/b.txt"])

    def test_comments_and_blank_lines_dropped(self) -> None:
        data = b"# a comment\r\nfile:///tmp/a.txt\r\n\r\n"
        self.assertEqual(parse_uri_list(data), ["file:///tmp/a.txt"])

    def test_empty_payload(self) -> None:
        self.assertEqual(parse_uri_list(b""), [])


class ParseGnomeCopiedFilesTests(unittest.TestCase):
    def test_copy_operation(self) -> None:
        data = b"copy\nfile:///tmp/a.txt\nfile:///tmp/b.txt\n"
        self.assertEqual(
            parse_gnome_copied_files(data), ("copy", ["file:///tmp/a.txt", "file:///tmp/b.txt"])
        )

    def test_cut_operation(self) -> None:
        data = b"cut\nfile:///tmp/a.txt\n"
        self.assertEqual(parse_gnome_copied_files(data), ("cut", ["file:///tmp/a.txt"]))

    def test_unrecognized_first_line_defaults_to_copy(self) -> None:
        data = b"whatever\nfile:///tmp/a.txt\n"
        self.assertEqual(parse_gnome_copied_files(data), ("copy", ["file:///tmp/a.txt"]))

    def test_empty_payload(self) -> None:
        self.assertEqual(parse_gnome_copied_files(b""), ("copy", []))


class UriToFilenameTests(unittest.TestCase):
    def test_plain_file_uri(self) -> None:
        self.assertEqual(uri_to_filename("file:///home/user/report.pdf"), "report.pdf")

    def test_percent_encoded_name(self) -> None:
        self.assertEqual(uri_to_filename("file:///home/user/My%20Report.pdf"), "My Report.pdf")

    def test_non_file_uri_returned_as_is(self) -> None:
        self.assertEqual(uri_to_filename("http://example.com/x.pdf"), "http://example.com/x.pdf")

    def test_root_level_file(self) -> None:
        self.assertEqual(uri_to_filename("file:///report.pdf"), "report.pdf")


if __name__ == "__main__":
    unittest.main()
