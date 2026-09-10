"""Consequential invariant: channel switching preserves active workspaces."""
from pathlib import Path
import tempfile
import unittest
from workspace import create, git, selected, state_directory, write_json

class WorkspaceIsolation(unittest.TestCase):
    def test_switch_preserves_dirty_workspace_and_fetches_new_tip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin, repo = root / 'origin', root / 'checkout'
            origin.mkdir()
            git(origin, 'init', '-b', 'main')
            git(origin, 'config', 'user.name', 'Fixture')
            git(origin, 'config', 'user.email', 'fixture@example.invalid')
            (origin / 'source').write_text('stable')
            git(origin, 'add', 'source')
            git(origin, 'commit', '-m', 'stable')
            stable = git(origin, 'rev-parse', 'HEAD')
            git(origin, 'checkout', '-b', 'agents')
            git(root, 'clone', str(origin), str(repo))
            first = create(repo, 'first')
            dirty = Path(first['path']) / 'source'
            dirty.write_text('active edits')
            write_json(state_directory(repo) / 'selection.json', {'channel': 'main'})
            self.assertEqual(create(repo, 'stable')['revision'], stable)
            (origin / 'source').write_text('new development')
            git(origin, 'commit', '-am', 'new development')
            write_json(state_directory(repo) / 'selection.json', {'channel': 'agents'})
            fresh = create(repo, 'fresh')
            self.assertEqual(fresh['revision'], git(origin, 'rev-parse', 'HEAD'))
            self.assertEqual(git(first['path'], 'rev-parse', 'HEAD'), first['revision'])
            self.assertEqual(dirty.read_text(), 'active edits')
            self.assertEqual(selected(repo), 'agents')
            self.assertEqual(git(repo, 'rev-parse', 'HEAD'), stable)

if __name__ == '__main__':
    unittest.main()
