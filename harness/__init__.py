"""Local acceptance catalog and explicitly registered, shell-free test runners."""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
CASE_ID = re.compile(r"(?:P[123]-[0-9]{2}|BASE-[0-9]{2})\Z")


class HarnessError(ValueError):
    """Invalid catalog, unsafe path, or ambiguous acceptance metadata."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HarnessError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def safe_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HarnessError(f"invalid relative path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise HarnessError(f"unsafe relative path: {value!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HarnessError(f"path escapes workspace: {value!r}")
    return path


def parse_cases(text: str, project: str, source: str) -> list[dict]:
    cases = []
    seen = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        case_id = cells[0]
        if not re.match(r"P[123]-", case_id):
            continue
        if not CASE_ID.fullmatch(case_id) or not case_id.startswith(project.upper() + "-"):
            raise HarnessError(f"invalid acceptance ID {case_id!r} in {source}")
        if case_id in seen or len(cells) < 2 or not cells[1]:
            raise HarnessError(f"duplicate or malformed acceptance row {case_id} in {source}")
        seen.add(case_id)
        cases.append(
            {
                "caseId": case_id,
                "project": project,
                "title": cells[1],
                "expected": " | ".join(cells[2:]),
                "source": source,
                "status": "planned",
                "runner": None,
            }
        )
    if not cases:
        raise HarnessError(f"no acceptance rows in {source}")
    return cases


def load_catalog(root: Path = ROOT) -> list[dict]:
    try:
        catalog = json.loads(
            safe_path(root, "harness/catalog.json").read_text(),
            object_pairs_hook=unique_object,
        )
        if catalog.get("schemaVersion") != 1:
            raise HarnessError("catalog schemaVersion must be 1")
        projects = catalog["projects"]
        if set(projects) != {"p1", "p2", "p3"}:
            raise HarnessError("catalog must declare p1, p2, and p3")
        for document in catalog["requiredDocuments"]:
            if not safe_path(root, document).is_file():
                raise HarnessError(f"required document missing: {document}")
        cases = []
        for project, spec in projects.items():
            source = spec["scope"]
            cases.extend(parse_cases(safe_path(root, source).read_text(), project, source))
        by_id = {case["caseId"]: case for case in cases}
        for case_id, runner in catalog["runners"].items():
            if not CASE_ID.fullmatch(case_id):
                raise HarnessError(f"invalid runner ID: {case_id}")
            if (
                runner["kind"]
                not in {"unittest_discovery", "python_json_report", "python_infrastructure_report"}
                or runner["project"] not in projects
            ):
                raise HarnessError(f"unsupported runner or project for {case_id}")
            timeout = runner["timeoutSeconds"]
            if runner["kind"] == "unittest_discovery":
                start = safe_path(root, runner["startDirectory"])
                pattern = runner["pattern"]
                if (
                    not start.is_dir()
                    or not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", pattern)
                    or not (start / pattern).is_file()
                ):
                    raise HarnessError(f"invalid unittest target for {case_id}")
            else:
                if set(runner) != {
                    "project",
                    "title",
                    "kind",
                    "script",
                    "timeoutSeconds",
                    "assertionFiles",
                    "mode",
                }:
                    raise HarnessError(f"invalid report runner fields for {case_id}")
                if (
                    type(runner["mode"]) is not str
                    or runner["mode"] not in {"offline", "lab", "live"}
                    or runner["kind"] == "python_infrastructure_report"
                    and runner["mode"] not in {"lab", "live"}
                ):
                    raise HarnessError(f"invalid report runner mode for {case_id}")
                assertion_files = runner["assertionFiles"]
                if (
                    type(assertion_files) is not list
                    or not 1 <= len(assertion_files) <= 32
                    or any(type(p) is not str for p in assertion_files)
                    or len(set(assertion_files)) != len(assertion_files)
                    or any(
                        not safe_path(root, p).is_file()
                        or Path(p).suffix not in {".py", ".ts", ".mjs"}
                        for p in assertion_files
                    )
                ):
                    raise HarnessError(f"invalid report assertion sources for {case_id}")
                script = safe_path(root, runner["script"])
                if (
                    not script.is_file()
                    or script.suffix != ".py"
                    or any(
                        p.is_symlink()
                        for p in (
                            root / runner["script"],
                            *(root / runner["script"]).parents,
                        )
                        if p != root.parent
                    )
                ):
                    raise HarnessError(f"invalid report runner script for {case_id}")
            maximum = 900 if runner["kind"] == "python_infrastructure_report" else 300
            if type(timeout) is not int or not 1 <= timeout <= maximum:
                raise HarnessError(f"invalid timeout for {case_id}")
            if case_id.startswith("BASE-"):
                case = {
                    "caseId": case_id,
                    "project": runner["project"],
                    "title": runner["title"],
                    "expected": "existing baseline suite",
                    "source": "harness/catalog.json",
                }
                cases.append(case)
                by_id[case_id] = case
            else:
                if case_id not in by_id or by_id[case_id]["project"] != runner["project"]:
                    raise HarnessError(f"runner has no matching scoped acceptance row: {case_id}")
                case = by_id[case_id]
            case.update(status="registered", runner=runner)
            if runner["kind"] in {"python_json_report", "python_infrastructure_report"}:
                case["mode"] = runner["mode"]
        return sorted(cases, key=lambda case: case["caseId"])
    except (
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as error:
        raise HarnessError(f"cannot load catalog: {error}") from error


def capture_text(value: bytes | str | None) -> str:
    """TimeoutExpired may return bytes even when subprocess text mode was requested."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else value


def execute(root: Path, case: dict) -> dict:
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    run_id = uuid4().hex
    directory = safe_path(root, f".local/harness/{run_id}")
    directory.mkdir(parents=True, exist_ok=False)
    stdout, stderr = "", ""
    runner = case["runner"]
    status, exit_code = "not_implemented", 2
    test_count, skipped_count, runner_exit_code = None, 0, None
    command = None
    external_report = None
    if runner is not None and runner["kind"] in {
        "python_json_report",
        "python_infrastructure_report",
    }:
        from .report_runner import execute_report

        outcome = execute_report(
            root,
            directory,
            safe_path(root, runner["script"]),
            case["caseId"],
            runner["timeoutSeconds"],
            expected_mode=case["mode"],
            infrastructure=runner["kind"] == "python_infrastructure_report",
        )
        status, exit_code, runner_exit_code = (
            outcome.status,
            outcome.exit_code,
            outcome.runner_exit_code,
        )
        test_count, skipped_count = outcome.test_count, outcome.skipped_count
        command, external_report = outcome.command, outcome.report
        stdout = (
            json.dumps({"event": "report_runner_result", "code": outcome.diagnostic_code}) + "\n"
        )
        if external_report is not None:
            (directory / "runner-result.json").write_text(json.dumps(external_report) + "\n")
    elif runner is not None:
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(safe_path(root, runner["startDirectory"])),
            "-p",
            runner["pattern"],
            "-v",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=runner["timeoutSeconds"],
                check=False,
            )
            stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
            runner_exit_code = result.returncode
            status = "passed" if exit_code == 0 else "failed"
            summaries = re.findall(r"^Ran (\d+) tests? in ", stderr, re.MULTILINE)
            test_count = int(summaries[-1]) if summaries else None
            skipped = re.search(r"\bskipped=(\d+)\b", stderr)
            skipped_count = int(skipped.group(1)) if skipped else 0
            if exit_code == 0 and not test_count:
                status, exit_code = "no_tests", 1
                stderr += "\nHarness rejected success without a positive unittest test count.\n"
            elif exit_code == 0 and skipped_count:
                status, exit_code = "incomplete", 2
        except subprocess.TimeoutExpired as error:
            stdout, stderr = capture_text(error.stdout), capture_text(error.stderr)
            status, exit_code = "timed_out", 124
        except OSError as error:
            stderr, status, exit_code = str(error), "runner_error", 1

    (directory / "stdout.txt").write_text(stdout)
    (directory / "stderr.txt").write_text(stderr)
    report = {
        "schemaVersion": 1,
        "runId": run_id,
        "caseId": case["caseId"],
        "project": case["project"],
        "status": status,
        "exitCode": exit_code,
        "runnerExitCode": runner_exit_code,
        "testCount": test_count,
        "skippedCount": skipped_count,
        "startedAt": started_at,
        "durationSeconds": round(time.monotonic() - started, 6),
        "command": command,
        "artifacts": {
            "report": str((directory / "report.json").relative_to(root.resolve())),
            "stdout": str((directory / "stdout.txt").relative_to(root.resolve())),
            "stderr": str((directory / "stderr.txt").relative_to(root.resolve())),
        },
    }
    if runner is not None and runner["kind"] in {
        "python_json_report",
        "python_infrastructure_report",
    }:
        report["mode"] = case["mode"]
        report["runnerReport"] = external_report
        if external_report is not None:
            report["artifacts"]["runnerResult"] = str(
                (directory / "runner-result.json").relative_to(root.resolve())
            )
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--project", choices=["p1", "p2", "p3", "all"], default="all")
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument("case_id", nargs="?")
    run.add_argument("--project", choices=["p1", "p2", "p3", "all"])
    args = parser.parse_args(argv)
    try:
        cases = load_catalog(root)
        if args.action == "validate":
            print(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "status": "valid",
                        "caseCount": len(cases),
                        "registered": sum(c["runner"] is not None for c in cases),
                    }
                )
            )
            return 0
        if args.action == "list":
            selected = [c for c in cases if args.project == "all" or c["project"] == args.project]
            print(json.dumps({"schemaVersion": 1, "cases": selected}, indent=2))
            return 0
        if bool(args.case_id) == bool(args.project):
            raise HarnessError("run requires either a case ID or --project, exclusively")
        selected = (
            [c for c in cases if c["caseId"] == args.case_id]
            if args.case_id
            else [c for c in cases if args.project == "all" or c["project"] == args.project]
        )
        if not selected:
            raise HarnessError(f"unknown case ID: {args.case_id}")
        reports = [execute(root, case) for case in selected]
        failed = any(
            r["status"] in {"failed", "timed_out", "runner_error", "no_tests"} for r in reports
        )
        pending = any(r["status"] in {"not_implemented", "incomplete"} for r in reports)
        status = "failed" if failed else "incomplete" if pending else "passed"
        print(json.dumps({"schemaVersion": 1, "status": status, "runs": reports}, indent=2))
        if len(reports) == 1:
            code = reports[0]["exitCode"]
            return code if code >= 0 else 1
        return 1 if failed else 2 if pending else 0
    except HarnessError as error:
        print(json.dumps({"schemaVersion": 1, "status": "invalid", "error": str(error)}))
        return 2
