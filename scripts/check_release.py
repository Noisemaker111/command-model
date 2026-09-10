"""Validate that a main PR is an explicitly pinned release with patch notes."""
import json
import os
from pathlib import Path
import re


def validate(pr):
    if pr['base']['ref'] != 'main':
        return
    if not pr['head']['ref'].startswith('release/agents-'):
        raise ValueError('Main accepts a frozen agents release candidate; prepare its release PR')
    marker = f"<!-- release-candidate: {pr['head']['sha']} -->"
    body = pr.get('body') or ''
    if marker not in body or '## Patch notes' not in body or not re.search(r'^- .+', body, re.MULTILINE):
        raise ValueError('Patch notes and exact candidate identity must be present in the release PR')
    if not re.search(r'<!-- release-base: [0-9a-f]{40} -->', body):
        raise ValueError('Release must record the prior stable source')


if __name__ == '__main__':
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    if 'pull_request' in event:
        validate(event['pull_request'])
    print('Release candidate metadata checked; only Jon may merge main.')
