"""Documentation policy fixtures catch metadata, link and source-reference drift."""

import json
import tempfile
import unittest
from pathlib import Path

from harness.documentation_check import audit_documents


def fixture_policy():
    return {
        "schemaVersion": 1,
        "include": ["README.md", "docs/*.md"],
        "requiredDocuments": ["README.md"],
        "statuses": ["Active", "Planned", "Completed", "Template"],
        "roles": [{"name": "readme", "patterns": ["README.md"], "requiredHeadings": ["Overview"]}],
        "forbiddenTerms": ["prohibitedcompany"],
        "forbiddenPatterns": [
            {
                "id": "hashed_source_url",
                "pattern": r"(?i)https?://github\.com/[^/\s]+/[^/\s]+/blob/[0-9a-f]{40}(?:/|\b)",
            },
            {
                "id": "explicit_source_identifier",
                "pattern": r"(?i)\bcommit(?:\s+(?:id|hash))?\s*[:=@]?\s*[`\"']?[0-9a-f]{7,40}\b",
            },
        ],
    }


VALID = """# Fixture project

Status: Active
Last reviewed: 9 November 2026

## Overview

Use explicit database commit boundaries.
"""

DESIGN_HEADINGS = [
    "Overview",
    "Objectives",
    "Functional requirements",
    "Non-functional requirements",
    "Back-of-the-envelope calculations",
    "High-level design",
    "Sequence diagram",
    "Low-level design",
    "Components and related details",
    "Security and privacy",
    "Observability",
    "Metrics",
    "Exception handling",
    "Design considerations and trade-offs",
    "Validation and acceptance gates",
]
TABLE = "| Kind | Requirement |\n| --- | --- |\n| Technical | Persist before acknowledgement |"
DIAGRAMS = {
    "High-level design": "flowchart TD\n    A[Client] --> B[Store]",
    "Sequence diagram": "sequenceDiagram\n    Client->>Store: accept",
    "Low-level design": "classDiagram\n    class Store\n    Store : accept()",
}


def design_fixture():
    text = "# Fixture design\n\nStatus: Active\nLast reviewed: 9 November 2026\n"
    for heading in DESIGN_HEADINGS:
        content = "This section records a reviewed boundary and its verification."
        if heading in {"Objectives", "Functional requirements", "Non-functional requirements"}:
            content = TABLE
        elif heading in DIAGRAMS:
            content = "```mermaid\n" + DIAGRAMS[heading] + "\n```"
        text += f"\n## {heading}\n\n{content}\n"
    return text


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "harness").mkdir()
        (self.root / "docs").mkdir()
        self.policy = fixture_policy()
        self.save_policy()
        (self.root / "README.md").write_text(VALID)

    def save_policy(self):
        (self.root / "harness/documentation.json").write_text(json.dumps(self.policy))

    def check(self, text):
        (self.root / "README.md").write_text(text)
        return audit_documents(self.root)

    def codes(self, report):
        return {problem["code"] for problem in report["violations"]}

    def prepare_design_policy(self):
        self.policy["include"].append("Design.md")
        self.policy["requiredDocuments"].append("Design.md")
        self.policy["roles"].append(
            {
                "name": "design",
                "patterns": ["Design.md"],
                "requiredHeadings": DESIGN_HEADINGS,
                "orderedHeadings": True,
                "requiredTables": [
                    "Objectives",
                    "Functional requirements",
                    "Non-functional requirements",
                ],
                "requiredDiagrams": {
                    "High-level design": ["flowchart", "graph"],
                    "Sequence diagram": ["sequenceDiagram"],
                    "Low-level design": ["classDiagram", "stateDiagram-v2"],
                },
            }
        )
        self.save_policy()

    def check_design(self, text):
        (self.root / "Design.md").write_text(text)
        return audit_documents(self.root)

    def test_standard_design_passes_without_applying_rules_to_readme(self):
        self.prepare_design_policy()
        report = self.check_design(design_fixture())
        self.assertEqual(report["status"], "documentation_checks_passed")
        self.assertEqual(report["documentsChecked"], 2)

    def test_reordered_and_duplicate_design_sections_fail(self):
        self.prepare_design_policy()
        text = design_fixture().replace("## Observability", "## Swap")
        text = text.replace("## Metrics", "## Observability").replace("## Swap", "## Metrics")
        self.assertIn("heading_order", self.codes(self.check_design(text)))
        self.assertIn(
            "duplicate_heading",
            self.codes(self.check_design(design_fixture() + "\n## Objectives\nAgain\n")),
        )

    def test_fenced_heading_cannot_supply_a_missing_design_section(self):
        self.prepare_design_policy()
        text = design_fixture().replace("## Objectives", "### Objectives")
        self.assertIn(
            "required_heading",
            self.codes(self.check_design(text + "\n```md\n## Objectives\n```\n")),
        )

    def test_empty_design_section_fails(self):
        self.prepare_design_policy()
        text = design_fixture().replace(
            "## Metrics\n\nThis section records a reviewed boundary and its verification.",
            "## Metrics\n",
        )
        self.assertIn("empty_section", self.codes(self.check_design(text)))

    def test_missing_fenced_and_header_only_tables_fail(self):
        self.prepare_design_policy()
        for table in ("No table.", "```md\n" + TABLE + "\n```", "\n".join(TABLE.splitlines()[:2])):
            with self.subTest(table=table):
                self.assertIn(
                    "required_table",
                    self.codes(self.check_design(design_fixture().replace(TABLE, table, 1))),
                )

    def test_malformed_table_separator_and_mismatched_columns_fail(self):
        self.prepare_design_policy()
        for table in (
            TABLE.replace("| --- | --- |", "| yes | yes |"),
            TABLE.replace("| Technical | Persist before acknowledgement |", "| Technical |"),
        ):
            with self.subTest(table=table):
                self.assertIn(
                    "required_table",
                    self.codes(self.check_design(design_fixture().replace(TABLE, table, 1))),
                )

    def test_escaped_pipes_remain_inside_table_cells(self):
        self.prepare_design_policy()
        table = TABLE.replace("Persist before acknowledgement", r"Keep A \| B distinct")
        self.assertEqual(
            self.check_design(design_fixture().replace(TABLE, table, 1))["status"],
            "documentation_checks_passed",
        )

    def test_indented_code_and_commented_tables_cannot_satisfy_policy(self):
        self.prepare_design_policy()
        for table in (
            "\n".join("    " + line for line in TABLE.splitlines()),
            "<!--\n" + TABLE + "\n-->",
            "<!-- " + TABLE.splitlines()[0] + " -->\n" + "\n".join(TABLE.splitlines()[1:]),
        ):
            with self.subTest(table=table):
                self.assertIn(
                    "required_table",
                    self.codes(self.check_design(design_fixture().replace(TABLE, table, 1))),
                )

    def test_table_in_another_section_cannot_supply_required_table(self):
        self.prepare_design_policy()
        text = design_fixture().replace(TABLE, "See the table below.", 1)
        self.assertIn("required_table", self.codes(self.check_design(text + "\n" + TABLE + "\n")))

    def test_wrong_empty_and_non_mermaid_diagrams_fail(self):
        self.prepare_design_policy()
        for before, after in (
            (DIAGRAMS["Sequence diagram"], DIAGRAMS["High-level design"]),
            (DIAGRAMS["Sequence diagram"], "sequenceDiagram\n%% no interactions"),
            ("```mermaid", "```text"),
        ):
            with self.subTest(after=after):
                self.assertIn(
                    "required_diagram",
                    self.codes(self.check_design(design_fixture().replace(before, after, 1))),
                )

    def test_diagram_must_belong_to_its_required_section(self):
        self.prepare_design_policy()
        block = "```mermaid\n" + DIAGRAMS["Sequence diagram"] + "\n```"
        text = design_fixture().replace(block, "See elsewhere.") + "\n" + block + "\n"
        self.assertIn("required_diagram", self.codes(self.check_design(text)))

    def test_commented_diagram_does_not_supply_required_evidence(self):
        self.prepare_design_policy()
        block = "```mermaid\n" + DIAGRAMS["Sequence diagram"] + "\n```"
        self.assertIn(
            "required_diagram",
            self.codes(
                self.check_design(design_fixture().replace(block, "<!--\n" + block + "\n-->"))
            ),
        )

    def test_single_line_mermaid_with_a_real_body_passes(self):
        self.prepare_design_policy()
        text = design_fixture().replace(
            DIAGRAMS["High-level design"], "flowchart TD; A[Client] --> B[Store]"
        )
        self.assertEqual(self.check_design(text)["status"], "documentation_checks_passed")
        text = text.replace("flowchart TD; A[Client] --> B[Store]", "flowchart TD; %% no graph")
        self.assertIn("required_diagram", self.codes(self.check_design(text)))

    def test_unclosed_diagram_is_not_accepted_as_evidence(self):
        self.prepare_design_policy()
        text = design_fixture().replace(
            "classDiagram\n    class Store\n    Store : accept()\n```",
            "classDiagram\n    class Store\n    Store : accept()",
        )
        codes = self.codes(self.check_design(text))
        self.assertIn("unbalanced_fence", codes)
        self.assertIn("required_diagram", codes)

    def test_tilde_fences_and_alternate_allowed_directives_pass(self):
        self.prepare_design_policy()
        text = design_fixture().replace("```", "~~~").replace("flowchart TD", "graph LR")
        text = text.replace(
            DIAGRAMS["Low-level design"],
            "stateDiagram-v2\n    [*] --> Accepted\n    Accepted --> Done",
        )
        self.assertEqual(self.check_design(text)["status"], "documentation_checks_passed")

    def test_invalid_design_rule_configuration_fails_closed(self):
        self.prepare_design_policy()
        self.check_design(design_fixture())
        original = json.loads(json.dumps(self.policy["roles"][-1]))
        variants = [
            {"orderedHeadings": "true"},
            {"requiredTables": ["Unknown section"]},
            {"requiredDiagrams": {"Sequence diagram": []}},
            {"requiredDiagrams": {"Sequence diagram": ["executable-script"]}},
            {"requiredDiagrams": {"Unknown section": ["flowchart"]}},
            {"requiredDiagrams": []},
            {
                "requiredDiagrams": {
                    "Sequence diagram": ["sequenceDiagram"],
                    "sequence diagram": ["flowchart"],
                }
            },
            {"requiredTables": ["Objectives", "objectives"]},
            {"unknownRule": True},
            {"requiredHeadings": ["Overview", "overview"]},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.policy["roles"][-1] = {**original, **variant}
                self.save_policy()
                self.assertEqual(audit_documents(self.root)["status"], "invalid")

    def test_valid_document_release_tag_and_sql_commit_pass(self):
        text = VALID + "\n[Version](https://github.com/org/repo/blob/v1.2.3/README.md)\n"
        text += "\n```sql\nBEGIN;\nCOMMIT;\n```\n"
        report = self.check(text)
        self.assertEqual(report["status"], "documentation_checks_passed")
        self.assertEqual(report["documentsChecked"], 1)

    def test_missing_or_duplicate_metadata_and_invalid_date_fail(self):
        variants = [
            VALID.replace("Status: Active\n", ""),
            VALID.replace("Status: Active", "Status: Done"),
            VALID + "\nStatus: Active\n",
            VALID.replace("Last reviewed: 9 November 2026", "Last reviewed: yesterday"),
            VALID + "\nLast reviewed: 9 November 2026\n",
        ]
        for text in variants:
            with self.subTest(text=text):
                self.assertTrue(
                    self.codes(self.check(text)) & {"status_metadata", "review_metadata"}
                )

    def test_review_date_is_parsed_instead_of_hardcoded(self):
        report = self.check(VALID.replace("9 November 2026", "12 December 2027"))
        self.assertEqual(report["status"], "documentation_checks_passed")

    def test_exactly_one_h1_ignores_fenced_examples(self):
        self.assertIn("document_title", self.codes(self.check(VALID + "\n# Second title\n")))
        report = self.check(VALID + "\n```md\n# Example heading\n```\n")
        self.assertNotIn("document_title", self.codes(report))

    def test_required_headings_are_case_insensitive_and_enforced(self):
        report = self.check(VALID.replace("## Overview", "## overview"))
        self.assertEqual(report["status"], "documentation_checks_passed")
        report = self.check(VALID.replace("## Overview", "## Other"))
        self.assertIn("required_heading", self.codes(report))

    def test_fences_match_marker_type_and_opening_length(self):
        for text in (VALID + "\n```sh\ncommand\n", VALID + "\n````md\n```\n"):
            with self.subTest(text=text):
                self.assertIn("unbalanced_fence", self.codes(self.check(text)))
        self.assertEqual(
            self.check(VALID + "\n~~~text\nexample\n~~~~\n")["status"],
            "documentation_checks_passed",
        )

    def test_broken_relative_link_fails_and_fenced_example_is_ignored(self):
        self.assertIn(
            "broken_link", self.codes(self.check(VALID + "\n[Missing](docs/missing.md)\n"))
        )
        report = self.check(VALID + "\n```md\n[Example](not-created.md)\n```\n")
        self.assertNotIn("broken_link", self.codes(report))

    def test_angle_link_spaces_fragment_and_reference_link_pass(self):
        (self.root / "docs/My note.md").write_text(VALID)
        text = VALID + "\n[Note](<docs/My note.md#ignored-fragment>)\n[Again][note]\n"
        text += "\n[note]: <docs/My note.md>\n"
        self.assertEqual(self.check(text)["status"], "documentation_checks_passed")

    def test_parent_link_within_root_passes_but_escape_and_symlink_fail(self):
        (self.root / "docs/note.md").write_text(VALID + "\n[Root](../README.md)\n")
        self.assertEqual(audit_documents(self.root)["status"], "documentation_checks_passed")
        self.assertIn("unsafe_link", self.codes(self.check(VALID + "\n[Escape](../outside.md)\n")))
        (self.root / "outside-link").symlink_to(self.root.parent, target_is_directory=True)
        self.assertIn(
            "unsafe_link", self.codes(self.check(VALID + "\n[Escape](outside-link/file.md)\n"))
        )

    def test_local_uri_schemes_and_absolute_paths_cannot_bypass_relative_links(self):
        targets = [
            "file:///etc/passwd",
            "file://localhost/etc/passwd",
            "C:/outside.md",
            str(self.root / "README.md"),
            "javascript:alert(1)",
        ]
        for target in targets:
            with self.subTest(target=target):
                self.assertIn(
                    "unsafe_link", self.codes(self.check(VALID + f"\n[Target]({target})\n"))
                )
        self.assertEqual(
            self.check(VALID + "\n[Public](https://example.com/page)\n")["status"],
            "documentation_checks_passed",
        )

    def test_prohibited_reference_and_source_ids_are_not_echoed(self):
        variants = [
            ("A prohibitedcompany reference.", "prohibited_reference"),
            ("https://github.com/org/repo/blob/" + "a" * 40 + "/README.md", "hashed_source_url"),
            ("commit id: abcdef1", "explicit_source_identifier"),
        ]
        for value, code in variants:
            with self.subTest(code=code):
                report = self.check(VALID + "\n" + value + "\n")
                self.assertIn(code, self.codes(report))
                self.assertNotIn(value, json.dumps(report))

    def test_required_file_and_policy_deletion_fail_closed(self):
        (self.root / "README.md").unlink()
        self.assertIn("missing_document", self.codes(audit_documents(self.root)))
        (self.root / "harness/documentation.json").unlink()
        report = audit_documents(self.root)
        self.assertEqual(report["status"], "invalid")
        self.assertIn("documentation_policy", self.codes(report))

    def test_policy_paths_and_discovered_symlinks_cannot_escape_root(self):
        self.policy["include"] = ["../*.md"]
        self.save_policy()
        self.assertEqual(audit_documents(self.root)["status"], "invalid")
        self.policy["include"] = ["README.md", "docs/*.md"]
        self.save_policy()
        (self.root / "docs/escaped.md").symlink_to(self.root.parent / "unread.md")
        # Discovery must validate a dangling link too, even without explicit registration.
        self.assertEqual(audit_documents(self.root)["status"], "invalid")

    def test_duplicate_policy_fields_and_invalid_regex_fail(self):
        path = self.root / "harness/documentation.json"
        path.write_text('{"schemaVersion": 1, "schemaVersion": 1}')
        self.assertEqual(audit_documents(self.root)["status"], "invalid")
        self.policy["forbiddenPatterns"][0]["pattern"] = "["
        self.save_policy()
        self.assertEqual(audit_documents(self.root)["status"], "invalid")

    def test_corpus_excludes_unrelated_nested_artifacts(self):
        (self.root / "docs/unrelated").mkdir()
        (self.root / "docs/unrelated/private.md").write_text("not a portfolio document")
        report = audit_documents(self.root)
        self.assertEqual(report["status"], "documentation_checks_passed")
        self.assertEqual(report["documentsChecked"], 1)


if __name__ == "__main__":
    unittest.main()
