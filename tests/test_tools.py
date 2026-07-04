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


def _git_spec(name="gittool", entry="gittool.py"):
    return tools.ToolSpec(name, name, ["username"], ["username"], "{bin} -u {target}",
                          install_method="git",
                          install_ref="https://github.com/example/gittool",
                          git_entry=entry)


def test_install_argv_git_uses_python_bootstrap():
    spec = _git_spec()
    argv, _ = tools.install_argv(spec, update=False)
    # Runs under a Python interpreter with the inlined bootstrap; ref + dest passed
    # as discrete argv elements (no shell), dest ends in the tool name.
    assert argv[1] == "-c"
    assert "git" in argv[2] and "clone" in argv[2]  # bootstrap source text
    assert argv[3] == "https://github.com/example/gittool"
    assert argv[4].replace("\\", "/").endswith("/tools/gittool")


def test_git_tool_not_installed_before_clone():
    spec = _git_spec("uncloned", "uncloned.py")
    assert tools.resolve_spec(spec) is None
    assert tools.tool_view(spec)["available"] is False
    with pytest.raises(FileNotFoundError):
        tools.build_tool_argv(spec, "someuser")


def test_parse_tool_findings_username_profiles():
    spec = tools.get_spec("sherlock")
    out = ("[+] Instagram: https://instagram.com/jdoe\n"
           "[+] GitHub: https://github.com/jdoe\n"
           "[-] Twitter: Not Found")
    s = tools.parse_tool_findings(spec, out)
    assert s and s["found"] is True and s["count"] == 2
    assert "https://github.com/jdoe" in s["profiles"]


def test_parse_tool_findings_domain_hosts():
    spec = tools.get_spec("subfinder")
    out = "api.example.com\nmail.example.com\nnot a host line here\ncdn.example.com\n"
    s = tools.parse_tool_findings(spec, out)
    assert s and s["count"] == 3
    # keyed as subdomains so the report's Related Domains picks them up
    assert "api.example.com" in s["subdomains"]


def test_parse_tool_findings_empty_returns_none():
    assert tools.parse_tool_findings(tools.get_spec("sherlock"), "") is None
    assert tools.parse_tool_findings(tools.get_spec("sherlock"), "   \n  ") is None


def test_git_tool_detected_and_run_after_clone(tmp_path_factory):
    import os
    spec = _git_spec("clonedtool", "clonedtool.py")
    dest = tools.TOOLS_DIR / spec.name
    dest.mkdir(parents=True, exist_ok=True)
    entry = dest / spec.git_entry
    entry.write_text("print('hi')\n")
    try:
        assert tools.resolve_spec(spec) == str(entry)
        assert tools.tool_view(spec)["available"] is True
        argv, stdin = tools.build_tool_argv(spec, "someuser")
        # Prepended with the system Python, then the entry script and its args.
        assert argv[0] == tools._system_python()
        assert argv[1] == str(entry)
        assert argv[-2:] == ["-u", "someuser"]
    finally:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
