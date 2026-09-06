"""Vendor shared setup into each standalone skill; --check detects drift."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
check = '--check' in sys.argv
for skill in sorted((root/'skills').glob('*/SKILL.md')):
    for source, relative in [('wqo.sh','scripts/wqo.sh'),('runtime.md','references/runtime.md')]:
        target = skill.parent/relative
        content = (root/'skill-support'/source).read_bytes()
        if check:
            if not target.exists() or target.read_bytes() != content:
                raise SystemExit(f'Run scripts/sync_skills.py: {target.relative_to(root)} differs')
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(content)
            if source.endswith('.sh'): target.chmod(0o755)
print('Standalone skill setup verified.' if check else 'Standalone skill setup synchronized.')
