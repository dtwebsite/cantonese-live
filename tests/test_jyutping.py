import tempfile
import unittest
from pathlib import Path

from cantonese_live import jyutping
from cantonese_live.asr import Utterance
from cantonese_live.config import UiConfig
from cantonese_live.pipeline import Line
from cantonese_live.transcript import TranscriptWriter
from cantonese_live.translate.base import Translation


class ToJyutpingTests(unittest.TestCase):
    def test_sentence_with_multi_char_words(self):
        got = jyutping.to_jyutping("我哋聽日落單，你畀個報價我先。")
        self.assertEqual(got, "ngo5 dei6 ting1 jat6 lok6 daan1, nei5 bei2 go3 bou3 gaa3 ngo5 sin1.")

    def test_numbers_and_latin_pass_through(self):
        got = jyutping.to_jyutping("300件 OK")
        self.assertIn("300", got)
        self.assertIn("OK", got)
        self.assertIn("gin6", got)

    def test_empty(self):
        self.assertEqual(jyutping.to_jyutping(""), "")

    def test_unavailable_backend_degrades_to_empty(self):
        self.assertEqual(jyutping.to_jyutping("你好", impl=None), "")

    def test_available_reports_backend(self):
        self.assertTrue(jyutping.available())


def _utt(start_s: float = 0.0) -> Utterance:
    return Utterance(text="你好", raw_text="你好", start_s=start_s, duration_s=1.0,
                     language="yue", emotion="", asr_seconds=0.1)


def _tr() -> Translation:
    return Translation(text="你好", engine="lexicon", changed_ratio=0.0)


class LineTests(unittest.TestCase):
    def test_line_has_optional_jyutping(self):
        line = Line(utterance=_utt(), translation=_tr(), latency_s=0.1)
        self.assertEqual(line.jyutping, "")
        line2 = Line(utterance=_utt(), translation=_tr(), latency_s=0.1, jyutping="nei5 hou2")
        self.assertEqual(line2.jyutping, "nei5 hou2")


class ConfigTests(unittest.TestCase):
    def test_show_jyutping_default_on(self):
        self.assertTrue(UiConfig().show_jyutping)


class TranscriptTests(unittest.TestCase):
    def test_with_jyutping_column(self):
        with tempfile.TemporaryDirectory() as d:
            w = TranscriptWriter(Path(d), engine="lexicon", jyutping=True)
            w.write(_utt(65.0), _tr(), jyutping="nei5 hou2")
            w.close()
            text = w.path.read_text(encoding="utf-8")
        self.assertIn("| 時間 | 粵語原文 | 粵拼 | 普通話 |", text)
        self.assertIn("| 01:05 | 你好 | nei5 hou2 | 你好 |", text)

    def test_without_jyutping_column_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            w = TranscriptWriter(Path(d), engine="lexicon")
            w.write(_utt(65.0), _tr())
            w.close()
            text = w.path.read_text(encoding="utf-8")
        self.assertIn("| 時間 | 粵語原文 | 普通話 |", text)
        self.assertIn("| 01:05 | 你好 | 你好 |", text)


if __name__ == "__main__":
    unittest.main()
