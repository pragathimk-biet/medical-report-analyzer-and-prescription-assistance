"""
Focused tests for the direct PDF export and the related display fixes.

Covers: /export-pdf response contract (status, Content-Type, attachment
filename), PDF validity via pypdf, export content (Case A Major interaction,
dataset IDs, DLTI research label, history limitation), exclusion of UI
controls, INTACT dataset notice, chatbot greeting, neutral title, and that the
client handler no longer uses print()/html2pdf.
"""

import io
import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pypdf import PdfReader

from app import app
from pdf_export import EXPORT_TITLE, build_analysis_pdf, pdf_filename
from prescription_reasoning_agent import _build_ddi_deterministic_block
from tests.test_ddi_checker import _make_loader_with_rows

ROOT = os.path.join(os.path.dirname(__file__), "..")
UI_CONTROL_TEXT = ("Download PDF", "Send Question", "Translate", "Ask Follow-Up", "Kannada")


def _pdf_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    return "\n".join(p.extract_text() or "" for p in reader.pages), reader


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestExportEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_success_is_attachment_pdf_with_dated_filename(self):
        res = self.client.post("/export-pdf", json={"markdown": "## Overall Summary\nHello.", "kind": "medicine"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["Content-Type"], "application/pdf")
        disp = res.headers["Content-Disposition"]
        self.assertIn("attachment", disp)
        self.assertRegex(disp, r'filename="?Prescription_Analysis_\d{4}-\d{2}-\d{2}\.pdf"?')
        self.assertTrue(res.data.startswith(b"%PDF-"))
        text, reader = _pdf_text(res.data)
        self.assertIn("Overall Summary", text)
        self.assertGreaterEqual(len(reader.pages), 1)

    def test_filename_prefix_by_kind(self):
        self.assertTrue(pdf_filename("report").startswith("Lab_Report_Analysis_"))
        self.assertTrue(pdf_filename("medicine").endswith(".pdf"))

    def test_empty_or_missing_markdown_is_json_error_not_pdf(self):
        for body in ({}, {"markdown": ""}, {"markdown": "   "}, {"markdown": 123}):
            res = self.client.post("/export-pdf", json=body)
            self.assertEqual(res.status_code, 400)
            self.assertIn("application/json", res.headers["Content-Type"])
            self.assertIn("error", res.get_json())
            self.assertNotIn("attachment", res.headers.get("Content-Disposition", ""))

    def test_oversized_markdown_rejected(self):
        res = self.client.post("/export-pdf", json={"markdown": "x" * 200_001})
        self.assertEqual(res.status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/export-pdf").status_code, 405)


class TestExportContentCaseA(unittest.TestCase):
    """Runs the real /upload-prescription route (Case A), then exports its output."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.loader = _make_loader_with_rows([
            ("DDInter1", "Warfarin", "DDInter20", "Acetylsalicylic acid", "Major"),
        ])

    def _case_a_markdown(self):
        old = app.config.get("DLTI_RESEARCH_PREVIEW_ENABLED")
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        try:
            with patch("app.PerceptionExtractionAgent.extract",
                       return_value=("1. Tab Warfarin 5mg once daily\n2. Tab Aspirin 75mg once daily",
                                     {"confidence": 0.95})), \
                 patch("ddi_checker.get_loader", return_value=self.loader), \
                 patch("app.generate_ai_analysis", return_value="Verified prescription summary."):
                res = self.client.post(
                    "/upload-prescription",
                    data={"file": (io.BytesIO(b"fake"), "rx.png")},
                    content_type="multipart/form-data",
                )
        finally:
            app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = old
        self.assertEqual(res.status_code, 200)
        return res.get_json()["analysis"]["english"]

    def test_export_preserves_case_a_content_and_limitations(self):
        md = self._case_a_markdown()
        res = self.client.post("/export-pdf", json={"markdown": md, "kind": "medicine"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["Content-Type"], "application/pdf")
        text, _ = _pdf_text(res.data)
        flat = re.sub(r"\s+", " ", text)
        self.assertIn("Major", flat)                                  # Case A interaction level
        self.assertIn("DDInter1", flat)                               # dataset IDs
        self.assertIn("DDInter20", flat)
        self.assertIn("Research preview", flat)                       # DLTI research label
        self.assertIn("Medication-Laboratory Interaction", flat)      # separate DLTI section
        self.assertIn("Drug-Drug Interaction", flat)                  # separate DDI section
        self.assertIn("BLOCKED_NO_AUTHORIZATION", flat)               # history limitation kept
        self.assertIn("PRESCRIPTION_ONLY", flat)
        self.assertIn("Disclaimer", flat)
        self.assertIn(EXPORT_TITLE.split(" \u2013 ")[0], flat)
        for ui in UI_CONTROL_TEXT:
            self.assertNotIn(ui, flat)

    def test_case_a_real_dataset_intact_has_no_contradictory_warning(self):
        old = app.config.get("DLTI_RESEARCH_PREVIEW_ENABLED")
        app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = True
        try:
            with patch("app.PerceptionExtractionAgent.extract",
                       return_value=("1. Tab Warfarin 5mg once daily\n2. Tab Aspirin 75mg once daily",
                                     {"confidence": 0.95})), \
                 patch("app.generate_ai_analysis", return_value="Verified prescription summary."):
                res = self.client.post(
                    "/upload-prescription",
                    data={"file": (io.BytesIO(b"fake"), "rx.png")},
                    content_type="multipart/form-data",
                )
        finally:
            app.config["DLTI_RESEARCH_PREVIEW_ENABLED"] = old
        md = res.get_json()["analysis"]["english"]
        self.assertIn("Dataset integrity | INTACT", md)
        self.assertNotIn("incomplete or has unverified integrity", md)
        self.assertNotIn("Notice on Dataset Integrity", md)
        self.assertIn("Major", md)                                   # real Case A record
        self.assertIn("PRESCRIPTION_ONLY", md)                       # history limitation kept
        self.assertIn("BLOCKED_NO_AUTHORIZATION", md)


class TestDatasetNoticeAndWording(unittest.TestCase):
    def _block(self, status):
        return _build_ddi_deterministic_block({
            "overall_status": "prescription_only",
            "coverage_completeness": "PRESCRIPTION_ONLY",
            "coverage": {"dataset_completeness_status": status,
                         "history_retrieval_status": "BLOCKED_NO_AUTHORIZATION"},
            "pair_results": [],
        })

    def test_intact_has_no_dataset_warning_but_keeps_history_limitation(self):
        out = self._block("INTACT")
        self.assertNotIn("incomplete or has unverified integrity", out)
        self.assertIn("PRESCRIPTION_ONLY", out)
        self.assertIn("BLOCKED_NO_AUTHORIZATION", out)

    def test_non_intact_statuses_still_warn(self):
        for status in ("PARTIAL", "EMPTY", "UNVERIFIED_NO_MANIFEST"):
            self.assertIn("Notice on Dataset Integrity", self._block(status))

    def test_chatbot_greeting_does_not_claim_history_loaded(self):
        html = _read("templates/index.html")
        self.assertNotIn("active medication history", html)
        self.assertIn("Patient medication history is not loaded", html)

    def test_neutral_title_replaces_official_clinical_summary(self):
        self.assertNotIn("official clinical ai summary", _read("static/js/main.js").lower())
        self.assertNotIn("official clinical ai summary", _read("pdf_export.py").lower())
        self.assertIn("Informational Research Prototype", EXPORT_TITLE)


class TestClientHandlerWiring(unittest.TestCase):
    def setUp(self):
        self.js = _read("static/js/main.js")
        start = self.js.index("download-pdf-btn")
        self.handler = self.js[start:start + 3500]

    def test_handler_uses_server_export_not_print_or_html2pdf(self):
        self.assertIn("/export-pdf", self.handler)
        self.assertNotIn("window.print", self.js)
        self.assertNotIn("html2pdf", self.js)
        self.assertNotIn("html2pdf", _read("templates/index.html"))

    def test_handler_checks_response_and_sets_filename(self):
        self.assertIn("response.ok", self.handler)
        self.assertIn("application/pdf", self.handler)
        self.assertIn("link.download = filename", self.handler)
        self.assertIn(".pdf", self.handler)


class TestPaginationPrimitives(unittest.TestCase):
    def test_headings_keep_with_next_and_short_doc_is_one_page(self):
        from pdf_export import _styles
        s = _styles()
        for level in (1, 2, 3, 4):
            self.assertTrue(s[level].keepWithNext)
        _, reader = _pdf_text(build_analysis_pdf("## A\ntext\n\n## B\ntext"))
        self.assertEqual(len(reader.pages), 1)

    def test_long_document_paginates_without_blank_page(self):
        md = "\n".join(f"## Section {i}\nParagraph {i} " + "word " * 60 for i in range(40))
        text, reader = _pdf_text(build_analysis_pdf(md))
        self.assertGreater(len(reader.pages), 1)
        for page in reader.pages:
            self.assertGreater(len((page.extract_text() or "").strip()), 40)
        self.assertIn("Section 39", text)


if __name__ == "__main__":
    unittest.main()
