"""Portable skill packaging and runner behavior; no BRAIN calls or global installs."""
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT/'skill-support/wqo.sh'


def test_standalone_skill_resources_and_links():
    skills=list((ROOT/'skills').glob('*/SKILL.md'))
    assert len(skills)==9
    for skill in skills:
        text=skill.read_text()
        assert re.search(r'^name: '+re.escape(skill.parent.name)+r'$',text,re.M)
        for link in re.findall(r'\]\(([^)]+)\)',text):
            if '://' not in link:
                resolved=(skill.parent/link).resolve()
                assert resolved.is_relative_to(skill.parent.resolve())
                assert resolved.is_file()
        assert (skill.parent/'scripts/wqo.sh').read_bytes()==RUNNER.read_bytes()
        assert (skill.parent/'references/runtime.md').read_bytes()==(ROOT/'skill-support/runtime.md').read_bytes()


def test_runner_reuses_cli_and_preserves_arguments_and_exit_status(tmp_path):
    binary=tmp_path/'wqo'
    binary.write_text('''#!/bin/bash
if [[ "$1" == "--version" ]]; then echo 'wqo 0.1.0'; exit 0; fi
printf '%s\\n' "$@"
exit 3
''')
    binary.chmod(0o755)
    env=dict(os.environ,PATH=str(tmp_path)+':/usr/bin:/bin')
    result=subprocess.run(['/bin/bash',str(RUNNER),'sim','run','--code','rank(close) + rank(volume)'],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==3
    assert result.stdout.splitlines()==['sim','run','--code','rank(close) + rank(volume)']
    assert not (tmp_path/'.wqo').exists()


def test_missing_prerequisites_fail_without_global_install(tmp_path):
    binary=tmp_path/'bin';binary.mkdir()
    for name in ('awk','mkdir','rmdir'):
        (binary/name).symlink_to(shutil.which(name))
    env=dict(os.environ,PATH=str(binary))
    result=subprocess.run(['/bin/bash',str(RUNNER),'--version'],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==1
    assert 'uv or Python 3.12+' in result.stderr
    assert not (tmp_path/'.wqo/install.lock').exists()
    assert not (tmp_path/'.wqo/venv').exists()


def test_installer_lock_does_not_run_requested_command(tmp_path):
    binary=tmp_path/'bin';binary.mkdir()
    for name in ('awk','mkdir','rmdir'):
        (binary/name).symlink_to(shutil.which(name))
    (tmp_path/'.wqo/install.lock').mkdir(parents=True)
    result=subprocess.run(['/bin/bash',str(RUNNER),'submit','DEMO_ALPHA','--confirm'],cwd=tmp_path,env=dict(os.environ,PATH=str(binary)),capture_output=True,text=True)
    assert result.returncode==1
    assert 'already running' in result.stderr
    assert (tmp_path/'.wqo/install.lock').exists()
