"""Functional coverage of shared features and the Codex lifecycle adapter."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Import the fixture module without exposing its test class to discovery again.
import test_autoresearch as fixtures
sys.path.insert(0, str(fixtures.RUNNER.parent))
from autoresearch import Session
from parity import confidence, project_root
from native_hooks import handle
from dashboard import page, terminal_lines
from finalize import finalize


class ParityTests(fixtures.ExperimentTests):
    # unittest inherits fixture tests; load_tests below selects only new methods.
    def test_delete_history_clears_both_layouts(self):
        self.baseline()
        self.cli('clear','--delete-history')
        self.assertFalse((self.root/'.auto/log.jsonl').exists())
        self.assertTrue((self.root/'.auto/measure.sh').exists())

    def test_full_report_embeds_current_segment_and_png_editor(self):
        self.baseline()
        result=self.cli('export','--full')
        report=Path(result['dashboard']).read_text()
        self.assertIn('downloadShareCard',report)
        self.assertIn('image/png',report)
        self.assertNotIn('__EMBEDDED_DATA__',report)
        self.assertIn('queueMicrotask(initializePage)',report)

    def test_skill_and_full_dashboard_include_revisit_protocol(self):
        root=fixtures.RUNNER.parent.parent
        skill=(root/'skills/autoresearch/SKILL.md').read_text()
        template=(root/'assets/full-dashboard.html').read_text()
        self.assertIn('--revisits-run N',skill)
        self.assertIn("prior discard's rollback reason",skill)
        self.assertIn('↻ Revisiting #',template)

    def test_compaction_preserves_long_rules_ideas_and_recent_learning(self):
        self.baseline(); self.cli('resume','--session-id','long-context')
        self.write('.auto/prompt.md','Rule. '*3000+'CRITICAL END RULE')
        self.write('.auto/ideas.md','Idea. '*3000+'FINAL IDEA')
        result=handle({'cwd':str(self.root),'session_id':'long-context','hook_event_name':'SessionStart','source':'compact'})
        context=result['hookSpecificOutput']['additionalContext']
        self.assertIn('CRITICAL END RULE',context)
        self.assertIn('FINAL IDEA',context)
        self.assertIn('## Recent experiments',context)
        self.assertIn('use measurement',context)

    def test_compaction_context_has_distinct_receipt(self):
        self.baseline()
        self.cli('resume','--session-id','owned')
        payload={'cwd':str(self.root),'session_id':'owned','hook_event_name':'SessionStart','source':'compact'}
        result=handle(payload)
        self.assertTrue(result['hookSpecificOutput']['additionalContext'].startswith('[Autoresearch hook: SessionStart source=compact]'))
        receipt=json.loads((self.root/'.auto/native-hook-events.jsonl').read_text().splitlines()[-1])
        self.assertEqual((receipt['event'],receipt['source'],receipt['outcome']),('SessionStart','compact','context_emitted'))
        self.cli('off'); self.assertEqual(handle(payload),{})
        self.assertEqual(json.loads((self.root/'.auto/native-hook-events.jsonl').read_text().splitlines()[-1])['outcome'],'inactive')

    def test_keep_tradeoff_preserves_best_and_records_reason(self):
        self.baseline(); self.begin(); self.write('value.txt', '12\n'); self.cli('run')
        result=self.cli('log','--status','keep','--description','tradeoff','--learned','less memory','--keep-reason','lower memory at acceptable latency')
        self.assertEqual(result['entry']['metric'],12)
        self.assertEqual(self.cli('status')['best'],10)
        self.assertEqual((self.root/'value.txt').read_text(),'12\n')
        self.assertIn('keep_reason',result['entry']['asi'])

    def test_manual_metrics_require_opt_in_and_checks_still_block_keep(self):
        self.write('.auto/measure.sh','echo "elapsed: ten milliseconds"\n')
        self.write('.auto/metrics.json','{"ms":10,"memory_mb":4}')
        self.begin(); self.assertEqual(self.cli('run','--manual-metrics')['outcome'],'ok')
        self.assertIn('primary metric',self.log(ok=False))
        result=self.cli('log','--status','keep','--description','parsed output','--learned','measured','--metrics-file',str(self.root/'.auto/metrics.json'))
        self.assertEqual(result['entry']['metric'],10)
        self.assertEqual(result['entry']['asi']['metric_source'],'agent-supplied')
        self.write('.auto/checks.sh','exit 1\n'); self.begin()
        self.assertEqual(self.cli('run','--manual-metrics')['outcome'],'checks_failed')
        self.assertIn('checks_failed',self.cli('log','--status','keep','--description','bad','--learned','bad','--metrics-file',str(self.root/'.auto/metrics.json'),ok=False))

    def test_repo_scope_commits_and_restores_additional_files(self):
        self.cli('init','--new-segment','--name','whole repo','--metric','ms','--scope','.')
        self.baseline(); self.begin(); self.write('other.txt','changed\n'); self.write('value.txt','9\n')
        self.cli('run'); self.log(); self.assertIn('other.txt',self.git('show','--format=','--name-only','HEAD'))
        self.begin(); self.write('extra.txt','temporary'); self.write('other.txt','regression')
        self.cli('run'); self.log('discard')
        self.assertFalse((self.root/'extra.txt').exists())
        self.assertEqual((self.root/'other.txt').read_text(),'changed\n')

    def test_duplicate_metrics_are_rejected_and_zero_timeouts_disable_deadlines(self):
        self.write('.auto/measure.sh','echo "METRIC ms=11"\necho "METRIC ms=10"\n')
        self.begin()
        result=self.cli('run','--timeout','0','--checks-timeout','0')
        self.assertEqual(result['outcome'],'crash')
        self.assertIn('Duplicate metric',result['metric_error'])

    def test_confidence_is_stable_and_resets_for_segment(self):
        rows=[{'metric':100,'status':'keep'}, {'metric':80,'status':'keep'}, {'metric':90,'status':'discard'}]
        self.assertEqual(confidence(rows,'lower'),2)
        self.assertEqual(confidence([dict(r,metric=200-r['metric']) for r in rows],'higher'),2)
        self.assertIsNone(confidence(rows[:2],'lower'))
        self.assertIsNone(confidence([{'metric':10,'status':'keep'}]*3,'lower'))
        self.baseline(); self.begin(); self.write('value.txt','8\n'); self.cli('run'); self.log()
        self.begin(); self.write('value.txt','9\n'); self.cli('run'); result=self.log('discard')
        self.assertEqual(result['entry']['confidence'],2)
        self.assertEqual(self.cli('status')['confidence'],2)
        self.init('--new-segment')
        self.assertIsNone(self.cli('status')['confidence'])

    def test_freeform_asi_survives(self):
        self.write('.auto/asi.json',json.dumps({'profile':{'hotspot':'parse','samples':[1,2]},'next_focus':'allocation'}))
        self.begin(); self.cli('run')
        result=self.cli('log','--status','keep','--description','baseline','--learned','profile saved','--asi-file',str(self.root/'.auto/asi.json'))
        self.assertEqual(result['entry']['asi']['profile']['samples'],[1,2])
        self.assertEqual(self.cli('status')['recent_runs'][0]['asi']['next_focus'],'allocation')

    def test_assumption_aware_revisit_is_validated_and_displayed(self):
        self.baseline()
        self.begin(); self.write('value.txt','12\n'); self.cli('run'); discarded=self.log('discard')
        discarded_run=discarded['entry']['run']
        self.begin(); self.write('value.txt','8\n'); self.cli('run')
        result=self.cli('log','--status','keep','--description','retry after cache removed old bottleneck',
                        '--learned','parallel path now wins','--revisits-run',str(discarded_run))
        self.assertEqual(result['entry']['asi']['revisits_run'],discarded_run)
        self.assertIn('invalidates a previous discard',result['next_iteration_guidance'])
        rendered='\n'.join(terminal_lines(Session(self.root).dashboard_data()))
        self.assertIn(f'↻ Revisiting #{discarded_run}',rendered)
        self.begin(); self.cli('run')
        error=self.cli('log','--status','discard','--description','bad reference','--learned','none',
                       '--next-action','new idea','--revisits-run','1',ok=False)
        self.assertIn('earlier discarded experiment',error)
        self.cli('abort','--reason','invalid revisit annotation')

    def test_secondary_schema_requires_complete_metrics_and_explicit_addition(self):
        self.write('.auto/measure.sh','echo "METRIC ms=10"\necho "METRIC memory_mb=20"\n')
        self.baseline()
        self.write('.auto/measure.sh','echo "METRIC ms=9"\n')
        self.begin(); self.cli('run')
        self.assertIn('Missing secondary',self.log(ok=False))
        self.cli('abort','--reason','fix measurement')
        self.write('.auto/measure.sh','echo "METRIC ms=9"\necho "METRIC memory_mb=20"\necho "METRIC compile_ms=1"\n')
        self.begin(); self.cli('run')
        self.assertIn('--force',self.log(ok=False))
        self.cli('log','--status','keep','--description','extra profiling','--learned','track compile cost','--force')
        self.assertEqual(self.cli('status')['secondaryMetrics'],[{'name':'compile_ms','unit':'ms'},{'name':'memory_mb','unit':'mb'}])

    def test_off_resume_and_clear_preserve_history(self):
        self.baseline(); self.cli('off')
        self.assertFalse(self.cli('status')['active'])
        self.assertIn('off',self.cli('begin','--hypothesis','should not run',ok=False))
        self.cli('resume'); self.begin(); self.cli('abort','--reason','done')
        result=self.cli('clear')
        self.assertTrue((Path(result['archived_to'])/'log.jsonl').exists())
        self.assertFalse((self.root/'.auto/log.jsonl').exists())
        self.assertTrue((self.root/'.auto/measure.sh').exists())
        self.init(); self.assertEqual(self.cli('status')['run_count'],0)

    def test_clear_refuses_pending(self):
        self.begin()
        self.assertIn('pending',self.cli('clear',ok=False))

    def test_unlimited_and_config_budget(self):
        self.cli('init','--new-segment','--name','unlimited','--metric','ms','--scope','value.txt')
        self.assertIsNone(self.cli('status')['remaining'])
        self.baseline()
        self.assertIsNone(self.cli('status')['remaining'])
        self.write('.auto/config.json','{"maxIterations": 7}')
        self.cli('init','--new-segment','--name','configured','--metric','ms','--scope','value.txt')
        self.assertEqual(self.cli('status')['remaining'],7)

    def test_workingdir_configuration_and_current_layout_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.auto').mkdir()
            (root/'.auto/config.json').write_text(json.dumps({'workingDir':str(self.root)}))
            self.assertEqual(project_root(root),self.root)
            (root/'.auto/config.json').unlink()
            (root/'.auto/prompt.md').write_text('new session')
            self.assertEqual(project_root(root),root.resolve())

    def test_legacy_flat_session_layout_runs_in_place_and_current_layout_wins(self):
        with tempfile.TemporaryDirectory(prefix='codex-autoresearch-legacy-') as folder:
            root=Path(folder).resolve()
            def git(*args):
                result=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return result.stdout.strip()
            git('init','-b','codex/legacy')
            git('config','user.email','test@example.invalid')
            git('config','user.name','Autoresearch Test')
            git('config','commit.gpgSign','false')
            (root/'value.txt').write_text('10\n')
            (root/'.gitignore').write_text('.auto/\nautoresearch*\n')
            git('add','value.txt','.gitignore'); git('commit','-m','base')
            (root/'autoresearch.sh').write_text('set -euo pipefail\necho "METRIC ms=$(cat value.txt)"\n')
            (root/'autoresearch.md').write_text('Legacy prompt survives')
            (root/'autoresearch.hooks').mkdir()
            (root/'autoresearch.hooks/before.sh').write_text('echo legacy-hook')
            (root/'autoresearch.hooks/before.sh').chmod(0o755)
            def cli(*args):
                result=subprocess.run([sys.executable,str(fixtures.RUNNER),'--project',str(root),*args],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            cli('init','--name','legacy','--metric','ms','--scope','value.txt','--max-iterations','2','--hooks')
            begun=cli('begin','--hypothesis','baseline')
            self.assertIn('legacy-hook',begun['hook']['tail'])
            self.assertEqual(cli('run')['metrics']['ms'],10)
            cli('log','--status','keep','--description','baseline','--learned','legacy works')
            self.assertTrue((root/'autoresearch.jsonl').exists())
            self.assertFalse((root/'.auto/log.jsonl').exists())
            self.assertEqual(cli('status')['baseline'],10)
            self.assertIn('Legacy prompt survives',cli('summary')['summary'])

            # Any current-layout session artifact selects the current protocol and
            # leaves stale legacy peers untouched.
            cli('clear','--delete-history')
            (root/'.auto/measure.sh').write_text('echo "METRIC ms=7"\n')
            (root/'autoresearch.sh').write_text('echo "METRIC ms=99"\n')
            cli('init','--name','current','--metric','ms','--scope','value.txt','--max-iterations','1')
            cli('begin','--hypothesis','current wins')
            self.assertEqual(cli('run')['metrics']['ms'],7)
            cli('log','--status','keep','--description','baseline','--learned','current wins')
            self.assertTrue((root/'.auto/log.jsonl').exists())

    def test_custom_command_only_without_fixed_benchmark(self):
        self.begin()
        self.assertIn('fixed',self.cli('run','--command','echo "METRIC ms=5"',ok=False))
        (self.root/'.auto/measure.sh').unlink()
        result=self.cli('run','--command','echo "METRIC ms=5"')
        self.assertEqual(result['metrics']['ms'],5)
        self.log()

    def test_summary_and_export_escape_untrusted_markup(self):
        self.write('.auto/prompt.md','# Keep correctness\nDo not change inputs')
        self.baseline()
        self.assertIn('Keep correctness',self.cli('summary')['summary'])
        session=Session(self.root)
        row=session.entries()[-1]
        row['description']='</script><script>alert(1)</script>'
        session.append(dict(row,run=2))
        output=self.cli('export')
        content=Path(output['dashboard']).read_text()
        self.assertNotIn(row['description'],content)
        self.assertIn('\\u003c/script\\u003e',content)
        self.assertIn('setInterval',content)
        self.assertIn('Save share card',content)

    def native_setup(self):
        self.baseline()
        self.cli('resume','--auto-resume','--session-id','owner')
        return {'cwd':str(self.root),'session_id':'owner','hook_event_name':'Stop','stop_hook_active':False}

    def test_native_continuation_is_owned_and_requires_progress(self):
        payload=self.native_setup()
        self.assertEqual(handle(dict(payload,session_id='other')), {})
        self.assertEqual(handle(payload)['decision'],'block')
        self.assertIn('no experiment progress',handle(dict(payload,stop_hook_active=True))['systemMessage'])
        self.assertFalse(self.cli('status')['active'])

    def test_native_interrupt_stops_without_waiting_for_benchmark_lock(self):
        payload=self.native_setup()
        with Session(self.root).lock():
            self.assertEqual(handle(dict(payload,hook_event_name='Interrupt')), {})
        self.assertEqual(handle(payload), {})
        self.assertFalse(self.cli('status')['active'])

    def test_native_compaction_rehydrates_and_off_suppresses(self):
        payload=self.native_setup()
        self.write('.auto/prompt.md','Unique research constraint')
        output=handle(dict(payload,hook_event_name='SessionStart',source='compact'))
        self.assertIn('Unique research constraint',output['hookSpecificOutput']['additionalContext'])
        self.cli('off')
        self.assertEqual(handle(dict(payload,hook_event_name='SessionStart',source='compact')), {})

    def test_native_guards_budget_turns_and_failures(self):
        payload=self.native_setup()
        session=Session(self.root)
        session.set_control(resumeTurns=200)
        self.assertIn('200 turns',handle(payload)['systemMessage'])
        self.cli('resume','--auto-resume','--session-id','owner')
        config=session.config(); config['maxIterations']=1
        (self.root/'.auto/codex.json').write_text(json.dumps(config))
        self.assertIn('budget',handle(payload)['systemMessage'])
        config['maxIterations']=None
        (self.root/'.auto/codex.json').write_text(json.dumps(config))
        self.cli('resume','--auto-resume','--session-id','owner')
        for n in range(21):
            session.append({'run':n+2,'metric':20,'status':'discard','session_id':config['session_id']})
        self.assertIn('20 consecutive',handle(payload)['systemMessage'])

    def test_finalize_independent_branches_include_deletion_and_union(self):
        base=self.git('rev-parse','HEAD')
        self.write('value.txt','8\n'); self.git('add','value.txt'); self.git('commit','-m','improve')
        (self.root/'other.txt').unlink(); self.git('add','other.txt'); self.git('commit','-m','remove unused')
        head=self.git('rev-parse','HEAD')
        plan={'base':base,'goal':'independent','groups':[{'slug':'speed','title':'Speed up','files':['value.txt']},{'slug':'remove','title':'Remove unused','files':['other.txt']}]}
        session=Session(self.root)
        self.assertTrue(finalize(session,plan)['dry_run'])
        result=finalize(session,plan,True)
        self.assertTrue(result['union_verified'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('show','codex/independent/01-speed:value.txt'),'8')
        self.assertEqual(self.git('show','codex/independent/01-speed:other.txt'),'preserve')
        deleted=subprocess.run(['git','cat-file','-e','codex/independent/02-remove:other.txt'],cwd=self.root,capture_output=True)
        self.assertNotEqual(deleted.returncode,0)

    def test_finalize_rejects_overlap_before_creating_branches(self):
        base=self.git('rev-parse','HEAD')
        self.write('value.txt','8\n'); self.git('add','value.txt'); self.git('commit','-m','change')
        plan={'base':base,'goal':'overlap','groups':[{'slug':'a','title':'a','files':['value.txt']},{'slug':'b','title':'b','files':['value.txt']}]}
        with self.assertRaisesRegex(ValueError,'overlap'):
            finalize(Session(self.root),plan,True)
        self.assertNotIn('codex/overlap',self.git('branch'))


def load_tests(loader, standard_tests, pattern):
    return unittest.TestSuite(ParityTests(name) for name in ParityTests.__dict__ if name.startswith('test_'))
