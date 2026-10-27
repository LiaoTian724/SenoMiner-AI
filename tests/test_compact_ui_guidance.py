import sys
import unittest
from unittest.mock import patch
from chem_pdf_extractor.app import parse_args
from chem_pdf_extractor.config import DEFAULT_MAX_CHARS


class CliTextCoverageTest(unittest.TestCase):
    def test_default_and_explicit_zero_do_not_truncate_cli_inputs(self):
        self.assertEqual(DEFAULT_MAX_CHARS,0)
        for argv in [['chem-pdf-extractor'],['chem-pdf-extractor','--max-chars','0']]:
            with self.subTest(argv=argv),patch.object(sys,'argv',argv):
                self.assertEqual(parse_args().max_chars,0)
