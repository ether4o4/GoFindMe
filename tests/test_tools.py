import sys

import pytest

from app import tools


def test_builtin_registry_has_core_tools():
    names = {s.name for s in tools.BUILTIN}
    for expected in ("sherlock", "holehe", "subfinder", "amass", "whois", "exiftool"):
        assert expected in names


def test_interactive_tools_not_auto_runnable():
    for s in tools.BUILTIN:
        if s.interactive:
            assert not s.auto_runnable, f"{s.name} interactive but auto_runnable"


def test_install_argv_pip():
    spec = tools.ToolSpec("x", "x", [], [], "{bin} {target}",
                          install_method="pip", install_ref="holehe")
    argv, _ = tools.install_argv(spec, update=False)
    assert argv == [sys.executable, "-m", "pip", "install", "holehe"]
    argv_u, _ = tools.install_argv(spec, update=True)
    assert "--upgrade" in argv_u


def test_install_argv_rejects_unsafe_pkg():
    spec = tools.ToolSpec("x", "x", [], [], "{bin} {target}",
                          install_method="pip", install_ref="holehe; rm -rf /")
    with pytest.raises(tools.ManageError):
        tools.install_argv(spec, update=False)


def test_install_argv_git_requires_https():
    spec = tools.ToolSpec("x", "x", [], [], "{bin} {target}",
                          install_method="git", install_ref="git@github.com:a/b")
    with pytest.raises(tools.ManageError):
        tools.install_argv(spec, update=False)


def test_install_argv_none_raises():
    spec = tools.ToolSpec("x", "x", [], [], "{bin} {target}", install_method="none")
    with pytest.raises(tools.ManageError):
        tools.install_argv(spec, update=False)


def test_build_tool_argv_refuses_interactive():
    spec = tools.ToolSpec("maltego", "true", ["x"], ["domain"], "{bin}",
                          auto_runnable=False, interactive=True)
    # 'true' exists on PATH, so it resolves; should still be refused as interactive.
    with pytest.raises(PermissionError):
        tools.build_tool_argv(spec, "example.com")


def test_build_tool_argv_missing_bin():
    spec = tools.ToolSpec("ghost", "definitely-not-a-real-binary-xyz", ["d"], ["domain"],
                          "{bin} {target}")
    with pytest.raises(FileNotFoundError):
        tools.build_tool_argv(spec, "example.com")
