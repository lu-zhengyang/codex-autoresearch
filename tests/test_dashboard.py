import json
import os
from pathlib import Path
import select
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
import test_autoresearch as fixtures
sys.path.insert(0,str(fixtures.RUNNER.parent))
from dashboard import terminal_lines
from autoresearch import Session


class DashboardTests(fixtures.ExperimentTests):
    def test_live_refresh_rejects_invalid_token_and_host(self):
        self.baseline()
        server=subprocess.Popen([sys.executable,str(fixtures.RUNNER),'--project',str(self.root),'dashboard','--serve'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(select.select([server.stdout],[],[],8)[0], 'Server did not start')
            line=server.stdout.readline()
            self.assertTrue(line,'Server exited before publishing its URL')
            url=json.loads(line)['url']
            with urllib.request.urlopen(url) as response:
                content=response.read().decode()
                self.assertIn('const live=true',content)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
            with urllib.request.urlopen(url+'/data') as response:
                self.assertEqual(json.load(response)['run_count'],1)
            self.begin(); self.write('value.txt','8\n'); self.cli('run'); self.log()
            with urllib.request.urlopen(url+'/data') as response:
                self.assertEqual(json.load(response)['best'],8)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url+'wrong')
            self.assertEqual(error.exception.code,404)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url,headers={'Host':'attacker.invalid'}))
            self.assertEqual(error.exception.code,403)
        finally:
            server.terminate()
            server.communicate(timeout=5)

    def test_terminal_view_contains_history_and_secondary(self):
        self.write('.auto/measure.sh','echo "METRIC ms=10"\necho "METRIC memory_mb=7"\n')
        self.baseline()
        lines=terminal_lines(Session(self.root).dashboard_data())
        self.assertIn('memory_mb','\n'.join(lines))
        self.assertIn('keep','\n'.join(lines))

    def test_native_dispatch_resolves_installed_paths(self):
        self.baseline(); self.cli('resume','--auto-resume','--session-id','test-task')
        root=fixtures.RUNNER.parent.parent
        payload={'cwd':str(self.root),'session_id':'test-task','hook_event_name':'SessionStart','source':'compact'}
        result=subprocess.run(['bash',str(root/'hooks/dispatch.sh')],input=json.dumps(payload),capture_output=True,text=True,
                              env=dict(os.environ,PLUGIN_ROOT=str(root),AUTORESEARCH_PYTHON=sys.executable))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'],'SessionStart')

    def test_off_blocks_an_already_begun_experiment(self):
        self.begin(); self.cli('off')
        self.assertIn('off',self.cli('run',ok=False))
        self.cli('resume'); self.cli('run'); self.log()


def load_tests(loader, standard_tests, pattern):
    return unittest.TestSuite(DashboardTests(name) for name in DashboardTests.__dict__ if name.startswith('test_'))
