"""Small structural checks; passing them does not certify planned product behavior."""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

from harness.root_unittest import run_root_tests

ROOT = Path(__file__).resolve().parent.parent
MODULES = {"p1", "p2", "p3"}
GROUPS = {"docs", "boundary", "contract"}
CONFIG_KEYS = {
    "schemaVersion",
    "module",
    "implementationStatus",
    "owners",
    "ownedPaths",
    "sourceRoots",
    "requiredDocuments",
    "forbiddenImports",
    "acceptance",
    "testMappings",
}
FOUNDATION_KEYS = {
    "schemaVersion",
    "ownedPaths",
    "sourceRoots",
    "requiredFiles",
    "requiredDocuments",
    "forbiddenImports",
}


class ContractError(ValueError):
    """Untrusted or ambiguous harness configuration."""


def safe_path(root, value):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or Path(value).is_absolute()
    ):
        raise ContractError(f"unsafe relative path: {value!r}")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ContractError(f"path escapes repository: {value!r}")
    return path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid config {path.name}: {error}") from error


def keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ContractError(f"{label}: expected fields {sorted(expected)}")


def string_list(value, label, allow_empty=False):
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ContractError(f"{label}: expected unique nonempty strings")


def load_contracts(root):
    rules = load_json(safe_path(root, "harness/rules/static.json"))
    keys(
        rules,
        {"schemaVersion", "groups", "sourceSuffixes", "ignoredDirectories"},
        "rules",
    )
    if type(rules["schemaVersion"]) is not int or rules["schemaVersion"] != 1:
        raise ContractError("rules schemaVersion must be 1")
    for name in ("groups", "sourceSuffixes", "ignoredDirectories"):
        string_list(rules[name], name)
    if set(rules["groups"]) != GROUPS:
        raise ContractError("rules groups must be docs, boundary, contract")
    if any(not re.fullmatch(r"\.[a-z]+", suffix) for suffix in rules["sourceSuffixes"]):
        raise ContractError("invalid source suffix")
    if any(
        "/" in name or "\\" in name or name in {".", ".."} for name in rules["ignoredDirectories"]
    ):
        raise ContractError("invalid ignored directory")
    modules_dir = safe_path(root, "harness/modules")
    if {p.stem for p in modules_dir.glob("*.json")} != MODULES:
        raise ContractError("module configs must declare exactly p1, p2, p3")
    configs = {}
    for module in sorted(MODULES):
        config = load_json(safe_path(root, f"harness/modules/{module}.json"))
        keys(config, CONFIG_KEYS, module)
        if (
            type(config["schemaVersion"]) is not int
            or config["schemaVersion"] != 1
            or config["module"] != module
            or config["implementationStatus"] not in {"planned", "partial", "implemented"}
        ):
            raise ContractError(f"{module}: invalid version, module, or implementation status")
        for field in ("owners", "ownedPaths", "requiredDocuments"):
            string_list(config[field], f"{module}.{field}")
        for field in ("ownedPaths", "requiredDocuments"):
            for path in config[field]:
                safe_path(root, path)
        if not isinstance(config["sourceRoots"], list) or not config["sourceRoots"]:
            raise ContractError(f"{module}: sourceRoots required")
        paths = []
        for source in config["sourceRoots"]:
            keys(source, {"path", "status"}, f"{module}.sourceRoots")
            safe_path(root, source["path"])
            paths.append(source["path"])
            if source["status"] not in {"planned", "implemented"}:
                raise ContractError(f"{module}: invalid source status")
        if len(paths) != len(set(paths)):
            raise ContractError(f"{module}: duplicate source root")
        if not isinstance(config["forbiddenImports"], list):
            raise ContractError(f"{module}: forbiddenImports must be a list")
        for rule in config["forbiddenImports"]:
            keys(rule, {"roots", "modules"}, f"{module}.forbiddenImports")
            string_list(rule["roots"], "boundary roots")
            string_list(rule["modules"], "forbidden modules")
            for path in rule["roots"]:
                safe_path(root, path)
                if not any(path == parent or path.startswith(parent + "/") for parent in paths):
                    raise ContractError(f"{module}: boundary root is outside its source roots")
        keys(config["acceptance"], {"scopeDocument", "prefix"}, f"{module}.acceptance")
        safe_path(root, config["acceptance"]["scopeDocument"])
        if config["acceptance"]["prefix"] != module.upper() + "-":
            raise ContractError(f"{module}: invalid acceptance prefix")
        if not isinstance(config["testMappings"], list):
            raise ContractError(f"{module}: testMappings must be a list")
        ids = []
        for mapping in config["testMappings"]:
            keys(mapping, {"caseId", "status", "testFiles"}, f"{module}.testMappings")
            case_id = mapping["caseId"]
            if (
                not isinstance(case_id, str)
                or not re.fullmatch(r"(?:" + module.upper() + r"|BASE)-[0-9]{2}", case_id)
                or mapping["status"] not in {"planned", "implemented"}
            ):
                raise ContractError(f"{module}: invalid test mapping")
            ids.append(case_id)
            string_list(
                mapping["testFiles"],
                "testFiles",
                allow_empty=mapping["status"] == "planned",
            )
            for path in mapping["testFiles"]:
                safe_path(root, path)
        if len(ids) != len(set(ids)):
            raise ContractError(f"{module}: duplicate case mapping")
        configs[module] = config
    return rules, configs


def load_foundation(root):
    """Mandatory infrastructure policy, independent of the three product modules."""
    config = load_json(safe_path(root, "harness/foundation.json"))
    keys(config, FOUNDATION_KEYS, "foundation")
    if type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1:
        raise ContractError("foundation schemaVersion must be 1")
    for field in ("ownedPaths", "requiredFiles", "requiredDocuments"):
        string_list(config[field], f"foundation.{field}")
        for relative in config[field]:
            safe_path(root, relative)
    if not isinstance(config["sourceRoots"], list) or not config["sourceRoots"]:
        raise ContractError("foundation: sourceRoots required")
    paths = []
    for source in config["sourceRoots"]:
        keys(source, {"path", "status"}, "foundation.sourceRoots")
        safe_path(root, source["path"])
        paths.append(source["path"])
        if source["status"] not in {"planned", "implemented"}:
            raise ContractError("foundation: invalid source status")
        if not any(belongs(source["path"], owner) for owner in config["ownedPaths"]):
            raise ContractError("foundation: source root has no declared owner")
    if len(paths) != len(set(paths)):
        raise ContractError("foundation: duplicate source root")
    for relative in config["requiredFiles"]:
        if not any(belongs(relative, owner) for owner in config["ownedPaths"]):
            raise ContractError("foundation: required file has no declared owner")
    if not isinstance(config["forbiddenImports"], list):
        raise ContractError("foundation: forbiddenImports must be a list")
    for rule in config["forbiddenImports"]:
        keys(rule, {"roots", "modules"}, "foundation.forbiddenImports")
        string_list(rule["roots"], "foundation boundary roots")
        string_list(rule["modules"], "foundation forbidden modules")
        for relative in rule["roots"]:
            safe_path(root, relative)
            if not any(belongs(relative, source) for source in paths):
                raise ContractError("foundation: boundary root is outside its source roots")
    return config


def belongs(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def changed_modules(paths, configs):
    selected = set()
    for path in paths:
        # Unknown paths and shared policy/configuration always expand to all.
        if path in {
            "AGENTS.md",
            "Design.md",
            "README.md",
            "pyproject.toml",
            ".gitignore",
        } or any(
            belongs(path, prefix)
            for prefix in (
                "harness",
                "scripts",
                "docs/portfolio-scope.md",
                "docs/validation-plan.md",
                "tests/test_harness",
            )
        ):
            return set(MODULES)
        owners = {
            name
            for name, config in configs.items()
            if any(belongs(path, prefix) for prefix in config["ownedPaths"])
        }
        if not owners:
            return set(MODULES)
        selected.update(owners)
    return selected


def git_changed_paths(root, base):
    if not base or base.startswith("-"):
        return None
    commands = [
        ["git", "rev-parse", "--verify", "HEAD"],
        ["git", "rev-parse", "--verify", base + "^{commit}"],
        ["git", "diff", "--name-only", "-z", base + "...HEAD", "--"],
        ["git", "diff", "--name-only", "-z", "--cached", "--"],
        ["git", "diff", "--name-only", "-z", "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    paths = set()
    try:
        for index, command in enumerate(commands):
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode:
                return None
            if index >= 2:
                paths.update(path for path in result.stdout.split("\0") if path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return sorted(paths)


def source_files(root, relative, rules):
    root = root.resolve()
    path = safe_path(root, relative)
    candidates = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
    for candidate in candidates:
        if (
            candidate.is_file()
            and candidate.suffix in rules["sourceSuffixes"]
            and not set(candidate.relative_to(root).parts) & set(rules["ignoredDirectories"])
        ):
            # Resolve each candidate too: a child symlink may escape an otherwise safe root.
            yield safe_path(root, candidate.relative_to(root).as_posix())


def import_targets(path, root=None):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        tree = ast.parse(text, filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level and root is not None:
                    package = path.relative_to(root).parent.parts
                    if node.level <= len(package):
                        parent = package[: len(package) - node.level + 1]
                        module = ".".join((*parent, module)) if module else ".".join(parent)
                yield module
                yield from (
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
    else:
        # A conservative syntax scan, not a replacement for the TS compiler/type checker.
        yield from re.findall(
            r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)["']([^"']+)["']""",
            text,
        )


def check_import_boundaries(root, rules, constraints, owner):
    failures = []
    for rule in constraints:
        for relative in rule["roots"]:
            for source in source_files(root, relative, rules):
                try:
                    imports = list(import_targets(source, root=root))
                except (SyntaxError, UnicodeError) as error:
                    raise ContractError(
                        f"cannot inspect {source.relative_to(root)}: {error}"
                    ) from error
                for target in imports:
                    normalized = target.replace(".", "/")
                    for forbidden in rule["modules"]:
                        name = forbidden.replace(".", "/")
                        if re.search(r"(?:^|[/@])" + re.escape(name) + r"(?:$|/)", normalized):
                            failures.append(
                                {
                                    **owner,
                                    "group": "boundary",
                                    "message": f"{source.relative_to(root)} imports forbidden dependency {target}",
                                }
                            )
    return failures


def check_modules(root, rules, configs, selected, groups):
    root = root.resolve()
    failures, summaries = [], []
    if "docs" in groups:
        from .documentation_check import check_documentation

        failures.extend(check_documentation(root))
    catalog = load_json(safe_path(root, "harness/catalog.json")) if "contract" in groups else None
    for module in sorted(selected):
        config = configs[module]
        summary = {
            "module": module,
            "implementationStatus": config["implementationStatus"],
            "groups": sorted(groups),
            "sources": [],
            "plannedAcceptanceCases": 0,
        }
        for source in config["sourceRoots"]:
            exists = safe_path(root, source["path"]).exists()
            summary["sources"].append({**source, "exists": exists})
            if source["status"] == "implemented" and (
                not exists or not any(source_files(root, source["path"], rules))
            ):
                failures.append(
                    {
                        "module": module,
                        "group": "contract",
                        "message": f"implemented source missing: {source['path']}",
                    }
                )
        if "docs" in groups:
            for document in config["requiredDocuments"]:
                path = safe_path(root, document)
                if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                    failures.append(
                        {
                            "module": module,
                            "group": "docs",
                            "message": f"required document missing or empty: {document}",
                        }
                    )
        if "contract" in groups:
            acceptance = config["acceptance"]
            path = safe_path(root, acceptance["scopeDocument"])
            if not path.is_file():
                raise ContractError(f"scope document missing: {acceptance['scopeDocument']}")
            ids = re.findall(r"^\|\s*`?(P[123]-\d{2})`?\s*\|", path.read_text(), flags=re.MULTILINE)
            if (
                not ids
                or len(ids) != len(set(ids))
                or any(not case.startswith(acceptance["prefix"]) for case in ids)
            ):
                raise ContractError(f"{module}: empty, duplicate, or wrong-project scope IDs")
            if (
                catalog.get("projects", {}).get(module, {}).get("scope")
                != acceptance["scopeDocument"]
            ):
                raise ContractError(f"{module}: scope disagrees with acceptance catalog")
            implemented = set()
            for mapping in config["testMappings"]:
                case = mapping["caseId"]
                if not case.startswith("BASE-") and case not in ids:
                    raise ContractError(f"{module}: mapped case absent from scope: {case}")
                if mapping["status"] == "implemented":
                    runner = catalog.get("runners", {}).get(case)
                    if (
                        not runner
                        or runner.get("project") != module
                        or runner.get("kind")
                        not in {
                            "unittest_discovery",
                            "python_json_report",
                            "python_infrastructure_report",
                        }
                    ):
                        raise ContractError(
                            f"{module}: implemented case has no registered runner: {case}"
                        )
                    if runner["kind"] == "unittest_discovery":
                        start, pattern = (
                            runner.get("startDirectory"),
                            runner.get("pattern"),
                        )
                        if (
                            not isinstance(start, str)
                            or not isinstance(pattern, str)
                            or not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", pattern)
                        ):
                            raise ContractError(f"{module}: invalid registered test target: {case}")
                        expected_files = [f"{start}/{pattern}"]
                    else:
                        expected_files = runner.get("assertionFiles")
                        script = runner.get("script")
                        if (
                            type(expected_files) is not list
                            or not 1 <= len(expected_files) <= 32
                            or any(type(path) is not str for path in expected_files)
                            or len(set(expected_files)) != len(expected_files)
                            or type(script) is not str
                            or not safe_path(root, script).is_file()
                            or not script.endswith(".py")
                            or type(runner.get("mode")) is not str
                            or runner.get("mode") not in {"offline", "lab", "live"}
                            or runner["kind"] == "python_infrastructure_report"
                            and runner["mode"] not in {"lab", "live"}
                            or type(runner.get("timeoutSeconds")) is not int
                            or not 1
                            <= runner["timeoutSeconds"]
                            <= (900 if runner["kind"] == "python_infrastructure_report" else 300)
                            or any(
                                Path(path).suffix not in {".py", ".ts", ".mjs"}
                                for path in expected_files
                            )
                        ):
                            raise ContractError(
                                f"{module}: invalid report assertion sources: {case}"
                            )
                    for test in mapping["testFiles"]:
                        if not safe_path(root, test).is_file():
                            raise ContractError(f"{module}: implemented test missing: {test}")
                    if mapping["testFiles"] != expected_files:
                        raise ContractError(f"{module}: test mapping disagrees with runner: {case}")
                    implemented.add(case)
            summary["plannedAcceptanceCases"] = len(set(ids) - implemented)
        if "boundary" in groups:
            failures.extend(
                check_import_boundaries(root, rules, config["forbiddenImports"], {"module": module})
            )
        summaries.append(summary)
    return failures, summaries


def check_foundation(root, rules, config, groups):
    """Check installed infrastructure on every selection, without acceptance IDs."""
    failures = []
    summary = {
        "policy": "harness/foundation.json",
        "groups": sorted(groups),
        "ownedPaths": config["ownedPaths"],
        "sources": [],
    }
    ignored = set(rules["ignoredDirectories"])
    for source in config["sourceRoots"]:
        path = safe_path(root, source["path"])
        present = path.is_file() and path.stat().st_size > 0
        if path.is_dir():
            # Contract roots may contain JSON-only fixtures, not executable code.
            for candidate in path.rglob("*"):
                if set(candidate.relative_to(root).parts) & ignored:
                    continue
                candidate = safe_path(root, candidate.relative_to(root).as_posix())
                if candidate.is_file() and candidate.stat().st_size > 0:
                    present = True
                    break
        summary["sources"].append({**source, "exists": path.exists(), "hasContent": present})
        if source["status"] == "implemented" and not present:
            failures.append(
                {
                    "area": "foundation",
                    "group": "contract",
                    "message": f"implemented foundation source missing: {source['path']}",
                }
            )
    for relative in config["requiredFiles"]:
        path = safe_path(root, relative)
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(
                {
                    "area": "foundation",
                    "group": "contract",
                    "message": f"required foundation file missing or empty: {relative}",
                }
            )
    if "docs" in groups:
        for relative in config["requiredDocuments"]:
            path = safe_path(root, relative)
            if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                failures.append(
                    {
                        "area": "foundation",
                        "group": "docs",
                        "message": f"required foundation document missing or empty: {relative}",
                    }
                )
    if "boundary" in groups:
        failures.extend(
            check_import_boundaries(root, rules, config["forbiddenImports"], {"area": "foundation"})
        )
    return failures, summary


def _timeout_progress(stderr: object) -> dict[str, str | int | float | None]:
    """Keep bounded code identifiers/timing only, never partial exception bodies."""
    if type(stderr) is bytes:
        text = stderr[-65536:].decode("utf-8", "replace")
    elif type(stderr) is str:
        text = stderr[-65536:]
    else:
        text = ""
    names = re.findall(
        r"^test[A-Za-z0-9_]{0,240} \(([A-Za-z_][A-Za-z0-9_.]{0,511})\) \.\.\.",
        text,
        re.MULTILINE,
    )
    summaries = re.findall(
        r"^Ran ([0-9]{1,7}) tests? in ([0-9]{1,6}(?:\.[0-9]{1,6})?)s$",
        text,
        re.MULTILINE,
    )
    return {
        "lastObservedTest": names[-1] if names else None,
        "observedTestCount": int(summaries[-1][0]) if summaries else None,
        "observedSeconds": float(summaries[-1][1]) if summaries else None,
    }


def run_tests(root, configs):
    root = root.resolve()
    starts = {"tests"}
    catalog = load_json(safe_path(root, "harness/catalog.json"))
    for config in configs.values():
        for mapping in config["testMappings"]:
            registered = catalog.get("runners", {}).get(mapping["caseId"], {})
            if (
                mapping["status"] == "implemented"
                and registered.get("kind") == "unittest_discovery"
            ):
                starts.update(
                    str(Path(path).parent) for path in mapping["testFiles"] if path.endswith(".py")
                )
    # New project Python suites are included even before a product acceptance runner is registered.
    for project in ("agent-continuity", "channel-continuity", "delegation-reliability"):
        directory = safe_path(root, f"projects/{project}/tests")
        if directory.is_dir():
            starts.add(directory.relative_to(root).as_posix())
    results = []
    for start in sorted(starts):
        safe_path(root, start)
        if start == "tests":
            results.append(run_root_tests(root, _timeout_progress))
            continue
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            start,
            "-p",
            "test_*.py",
            "-v",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            summaries = re.findall(r"^Ran (\d+) tests? in ", result.stderr, re.MULTILINE)
            test_count = int(summaries[-1]) if summaries else 0
            skipped = re.search(r"\bskipped=(\d+)\b", result.stderr)
            skipped_count = int(skipped.group(1)) if skipped else 0
            effective_code = result.returncode
            status = "passed" if effective_code == 0 else "failed"
            if effective_code == 0 and (test_count == 0 or skipped_count):
                effective_code = 1
                status = "no_tests" if test_count == 0 else "skipped_tests"
            results.append(
                {
                    "command": command,
                    "exitCode": effective_code,
                    "runnerExitCode": result.returncode,
                    "status": status,
                    "testCount": test_count,
                    "skippedCount": skipped_count,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        except subprocess.TimeoutExpired as error:
            results.append(
                {
                    "command": command,
                    "exitCode": 124,
                    "stderr": "test suite exceeded 120 seconds",
                    "timeoutProgress": _timeout_progress(error.stderr),
                }
            )
    return results


def main(argv=None, root=ROOT):
    root = root.resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=["p1", "p2", "p3", "all"], default="all")
    parser.add_argument("--groups", default="docs,boundary,contract")
    parser.add_argument("--changed", action="store_true")
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args(argv)
    try:
        groups = set(args.groups.split(","))
        if not groups or not groups <= GROUPS:
            raise ContractError("unknown or empty groups")
        rules, configs = load_contracts(root)
        foundation = load_foundation(root)
        selected = MODULES if args.module == "all" else {args.module}
        selection = "explicit"
        if args.changed:
            paths = git_changed_paths(root, args.base)
            selected = MODULES if paths is None else changed_modules(paths, configs)
            if args.module != "all":
                selected = set(selected) | {args.module}
            selection = "all_no_git_baseline" if paths is None else "changed_conservative"
        failures, summaries = check_modules(root, rules, configs, selected, groups)
        foundation_failures, foundation_summary = check_foundation(root, rules, foundation, groups)
        failures.extend(foundation_failures)
        test_results = run_tests(root, configs) if args.run_tests and not failures else []
        failed = bool(failures) or any(result["exitCode"] for result in test_results)
        report = {
            "schemaVersion": 1,
            "status": "failed" if failed else "structural_checks_passed",
            "productAcceptance": "not_certified",
            "selection": selection,
            "testSelection": "all_implemented_python_suites" if args.run_tests else "not_requested",
            "validatedConfigs": sorted(configs),
            "modules": summaries,
            "foundation": foundation_summary,
            "violations": failures,
            "tests": test_results,
        }
        print(json.dumps(report, indent=2))
        return 1 if failed else 0
    except (ContractError, OSError, TypeError, AttributeError) as error:
        print(json.dumps({"schemaVersion": 1, "status": "invalid", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
