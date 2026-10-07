from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ENVIRONMENT, FakeHarness, fake_git_install, skill_ci, write, write_skill

from skill_ci import config
from skill_ci.config import ConfigError, Tag, Track
from skill_ci.runs import Agent
from skill_ci.suite import PiiScope

INSTALLED_COMMIT = "0" * 40


def problems(error: ConfigError) -> list[str]:
    return [line.split(": ", 1)[1] for line in str(error).splitlines()]


class ConfigFileTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-config-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(contextlib.chdir(self.root))
        self.path = self.root / ".skill-ci.toml"

    def write(self, text: str) -> Path:
        return write(self.path, text)

    def test_each_version_kind(self) -> None:
        for text, version in (
            ("v1.2.3", Tag(1, 2, 3)),
            ("v0.10.0", Tag(0, 10, 0)),
            ("latest", Track.LATEST),
            ("main", Track.MAIN),
        ):
            with self.subTest(text=text):
                pin = config.read(self.write(f'version = "{text}"\n')).pin
                self.assertEqual(pin.version, version)
                self.assertEqual(pin.source, "https://github.com/mdsmithaustin/skill-ci.git")

    def test_any_other_version_is_rejected(self) -> None:
        for line, shown in (
            ('version = "v1"', "'v1'"),
            ('version = "1.2.3"', "'1.2.3'"),
            ('version = "v1.02.3"', "'v1.02.3'"),
            ('version = "v1.2.3-rc.1"', "'v1.2.3-rc.1'"),
            ('version = "Latest"', "'Latest'"),
            ("version = 1", "1"),
            ('skills_dir = "skills"', "missing"),
        ):
            with self.subTest(line=line):
                with self.assertRaises(ConfigError) as caught:
                    config.read(self.write(line + "\n"))
                self.assertEqual(problems(caught.exception), [f"version is {shown}; set it to latest, main, or a tag such as v1.0.0"])

    def test_a_bad_version_and_an_unknown_key_are_reported_together(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            config.read(self.write('version = "v1"\nskils_dir = "skills"\n'))
        self.assertEqual(
            str(caught.exception).splitlines(),
            [
                ".skill-ci.toml: version is 'v1'; set it to latest, main, or a tag such as v1.0.0",
                ".skill-ci.toml: unknown key 'skils_dir'; did you mean 'skills_dir'?",
            ],
        )

    def test_an_unknown_key_is_returned_with_a_file_that_is_otherwise_valid(self) -> None:
        text = 'version = "main"\nskils_dir = "skills"\nruns = 5\nflavor = "mint"\n'
        loaded = config.read(self.write(text))
        self.assertEqual(loaded.unknown_keys, ("unknown key 'skils_dir'; did you mean 'skills_dir'?", "unknown key 'flavor'"))
        self.assertEqual(loaded.settings, {"runs": 5})
        ignoring = config.read(self.path, ignore_unknown=True)
        self.assertEqual((ignoring.unknown_keys, ignoring.settings), ((), {"runs": 5}))

    def test_a_known_problem_comes_before_an_unknown_key(self) -> None:
        self.write('version = "main"\nskils_dir = "skills"\nruns = "five"\nflavor = "mint"\n')
        with self.assertRaises(ConfigError) as caught:
            config.read(self.path)
        self.assertEqual(
            problems(caught.exception),
            ["runs is 'five'; set it to a whole number", "unknown key 'skils_dir'; did you mean 'skills_dir'?", "unknown key 'flavor'"],
        )
        with self.assertRaises(ConfigError) as ignoring:
            config.read(self.path, ignore_unknown=True)
        self.assertEqual(problems(ignoring.exception), ["runs is 'five'; set it to a whole number"])

    def test_settings_take_the_types_their_flags_parse_to(self) -> None:
        path = self.write(
            "\n".join(
                (
                    'version = "latest"',
                    'skills_dir = "skills"',
                    'evals_dir = "evals"',
                    'pii_scope = "repository"',
                    "require_manifests = true",
                    "package = false",
                    "runs = 5",
                    'agents = ["codex"]',
                    'codex_cmd = "codex exec"',
                    "",
                )
            )
        )
        self.assertEqual(
            config.read(path).settings,
            {
                "skills_dir": Path("skills"),
                "evals_dir": Path("evals"),
                "pii_scope": PiiScope.REPOSITORY,
                "require_manifests": True,
                "package": False,
                "runs": 5,
                "agents": [Agent.CODEX],
                "codex_cmd": "codex exec",
            },
        )

    def test_a_wrong_value_names_its_key(self) -> None:
        path = self.write('version = "main"\nrequire_manifests = "yes"\npii_scope = "all"\nruns = true\nagents = []\nskills_dir = 3\n')
        with self.assertRaises(ConfigError) as caught:
            config.read(path)
        self.assertEqual(
            problems(caught.exception),
            [
                "require_manifests is 'yes'; set it to true or false",
                "pii_scope is 'all'; set it to one of skills, repository",
                "runs is True; set it to a whole number",
                "agents is []; set it to a nonempty list",
                "skills_dir is 3; set it to a string",
            ],
        )

    def test_unreadable_toml_names_the_file(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            config.read(self.write("version = \n"))
        self.assertRegex(str(caught.exception), r"^\.skill-ci\.toml: cannot read: ")

    def test_source_forms(self) -> None:
        mirror = self.root / "mirror.git"
        for value, source in (
            ("https://git.example.com/skill-ci.git", "https://git.example.com/skill-ci.git"),
            ("ssh://git@example.com/org/skill-ci.git", "ssh://git@example.com/org/skill-ci.git"),
            ("https://git.example.com/a%20b.git", "https://git.example.com/a%20b.git"),
            ("file:///srv/skill-ci.git", "file:///srv/skill-ci.git"),
            ("mirror.git", mirror.as_uri()),
            (str(mirror), mirror.as_uri()),
            ("my mirror#1.git", (self.root / "my mirror#1.git").as_uri()),
        ):
            with self.subTest(value=value):
                self.assertEqual(config.read(self.write(f'version = "main"\nsource = "{value}"\n')).pin.source, source)
        for value, problem in (
            ("git@example.com:org/skill-ci.git", "is an scp-style address; write it as ssh://user@host/path"),
            ("ftp://git.example.com/skill-ci.git", "uses ftp; use one of https, ssh, file"),
            ("http://git.example.com/skill-ci.git", "uses http; use one of https, ssh, file"),
            ("git://git.example.com/skill-ci.git", "uses git; use one of https, ssh, file"),
            ("https://git.example.com/skill-ci.git#subdirectory=x", "contains '#'; percent-encode it or remove it"),
            ("https://git.example.com/skill-ci.git?ref=main", "contains '?'; percent-encode it or remove it"),
            ("https://git.example.com/a b.git", "contains ' '; percent-encode it or remove it"),
            ("https://", "names no host"),
            ("ssh:///org/skill-ci.git", "names no host"),
            ("file://relative/skill-ci.git", "names no absolute path; write file:///absolute/path, or a plain path"),
            ("   ", "is not a git URL or a path"),
        ):
            with self.subTest(value=value), self.assertRaises(ConfigError) as caught:
                config.read(self.write(f'version = "main"\nsource = "{value}"\n'))
            self.assertEqual(problems(caught.exception), [f"source {value!r} {problem}"])

    def test_a_relative_source_resolves_from_the_file_not_the_working_directory(self) -> None:
        nested = self.root / "skills" / "example"
        nested.mkdir(parents=True)
        path = self.write('version = "main"\nsource = "../mirror.git"\n')
        os.chdir(nested)
        self.assertEqual(config.read(path).pin.source, (self.root.parent / "mirror.git").as_uri())

    def test_the_nearest_file_up_to_the_repository_root_applies(self) -> None:
        nested = self.root / "repository" / "skills" / "example"
        nested.mkdir(parents=True)
        self.write('version = "main"\n')
        self.assertIsNone(config.find(nested), "outside a repository only the current directory counts")
        self.assertEqual(config.find(self.root), self.path)
        (self.root / "repository" / ".git").mkdir()
        self.assertIsNone(config.find(nested), "a file above the repository root belongs to another project")
        inner = write(self.root / "repository" / ".skill-ci.toml", 'version = "main"\n')
        self.assertEqual(config.find(nested), inner)

    def test_with_version_rewrites_only_the_version_value(self) -> None:
        text = "# skill-ci pin\nversion = 'v0.9.0'  # bump with skill-ci update\n\nskills_dir = \"skills\"  # version = 'kept'\n"
        self.assertEqual(
            config.with_version(text, Tag(0, 10, 0)),
            "# skill-ci pin\nversion = 'v0.10.0'  # bump with skill-ci update\n\nskills_dir = \"skills\"  # version = 'kept'\n",
        )
        with self.assertRaises(ValueError):
            config.with_version('skills_dir = "skills"\n', Tag(0, 10, 0))


class FlagPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skill-ci-flags-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "checkout"
        write_skill(self.checkout / "skills" / "example")
        environment = {**ENVIRONMENT, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        subprocess.run(["git", "init", "-q"], cwd=self.checkout, env=environment, capture_output=True, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.checkout, env=environment, capture_output=True, check=True)
        self.environment = {
            **environment,
            "PYTHONPATH": str(fake_git_install(self.root / "installed", INSTALLED_COMMIT)),
            "SKILL_CI_PINNED": INSTALLED_COMMIT,
        }

    def settings(self, *lines: str) -> None:
        write(self.checkout / ".skill-ci.toml", "\n".join(('version = "v1.0.0"', *lines, "")))

    def run_cli(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return skill_ci(*arguments, cwd=cwd or self.checkout, env=self.environment)

    def test_a_flag_replaces_the_file_value(self) -> None:
        self.settings('skills_dir = "elsewhere"')
        from_file = self.run_cli("lint")
        self.assertNotEqual(from_file.returncode, 0, from_file.stdout + from_file.stderr)
        self.assertIn("elsewhere", from_file.stdout + from_file.stderr)
        from_flag = self.run_cli("lint", "--skills-dir", "skills")
        self.assertEqual(from_flag.returncode, 0, from_flag.stdout + from_flag.stderr)
        self.assertEqual(from_flag.stdout.splitlines()[-1], "checks run: 2; failed: 0")

    def test_a_no_flag_turns_off_a_switch_the_file_turns_on(self) -> None:
        self.settings("require_manifests = true")
        from_file = self.run_cli("check")
        self.assertEqual(from_file.returncode, 1, from_file.stdout + from_file.stderr)
        self.assertIn("skill-ci: require-manifests is enabled, but no manifest files were checked", from_file.stderr)
        from_flag = self.run_cli("check", "--no-require-manifests")
        self.assertEqual(from_flag.returncode, 0, from_flag.stdout + from_flag.stderr)

    def test_paths_in_the_file_resolve_from_its_directory(self) -> None:
        self.settings('skills_dir = "skills"')
        result = self.run_cli("lint", cwd=self.checkout / "skills" / "example")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["checks run: 2; failed: 0"])
        self.assertEqual(result.stderr.splitlines(), ["frontmatter: 1 skills, 0 errors", "content: 1 files, 0 findings"])

    def test_a_repeated_flag_replaces_the_file_list(self) -> None:
        self.settings('agents = ["codex"]')
        fake = FakeHarness(self.root)
        fake_git_install(fake.purelib, INSTALLED_COMMIT)
        for flags, agent in (((), "codex"), (("--agent", "claude"), "claude")):
            with self.subTest(flags=flags):
                fake.log.unlink(missing_ok=True)
                result = fake.run("run", "skills/example", "--out", "out", *flags, cwd=self.checkout, SKILL_CI_PINNED=INSTALLED_COMMIT)
                self.assertEqual(result.returncode, 0, result.stderr)
                runs = [stage[:3] for stage in fake.arguments() if stage[0] == "run-agent"]
                self.assertEqual(runs, [["run-agent", "--agent", agent]])

    def test_a_bad_file_stops_every_command_with_each_problem(self) -> None:
        write(self.checkout / ".skill-ci.toml", 'version = "v1"\nskils_dir = "skills"\n')
        result = skill_ci("check", cwd=self.checkout, env={key: value for key, value in self.environment.items() if key != "SKILL_CI_PINNED"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "skill-ci: .skill-ci.toml: version is 'v1'; set it to latest, main, or a tag such as v1.0.0",
                "skill-ci: .skill-ci.toml: unknown key 'skils_dir'; did you mean 'skills_dir'?",
            ],
        )


if __name__ == "__main__":
    unittest.main()
