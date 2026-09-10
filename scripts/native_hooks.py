"""Codex lifecycle adapter: no tool approvals, background agents, or trust overrides."""
import json
from pathlib import Path
import sys
import time
import os
from autoresearch import Session
from parity import project_root


def receipt(session, payload, outcome):
    # Metadata only: never copy prompts, transcripts, or environment values.
    record = {'time': time.time(), 'event': payload.get('hook_event_name'),
              'source': payload.get('source'), 'outcome': outcome}
    encoded = (json.dumps(record, allow_nan=False) + '\n').encode()
    try:
        fd = os.open(session.auto / 'native-hook-events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
    except OSError:
        pass  # Diagnostics must not prevent context delivery or interruption.


def handle(payload):
    event = payload.get('hook_event_name')
    if event not in ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt') or not payload.get('cwd'):
        return {}
    root = project_root(payload['cwd'])
    if not (root / '.auto/codex.json').is_file():
        return {}
    session = Session(root)
    control = session.control()
    owner = control.get('owner_session')
    # Never reactivate or steer a different task merely because it shares a checkout.
    if not owner or owner != payload.get('session_id'):
        return {}
    if event == 'Interrupt':
        # Atomic write without acquiring the long-running benchmark lock; off is immediate.
        (session.auto / 'stopped').touch()
        receipt(session, payload, 'stopped')
        return {}
    if not control.get('active'):
        receipt(session, payload, 'inactive')
        return {}
    with session.lock():
        state = session.status()
        if event in ('SessionStart', 'UserPromptSubmit'):
            source = payload.get('source')
            source = source if source in ('startup', 'resume', 'clear', 'compact') else 'unspecified'
            label = event + (' source=' + source if event == 'SessionStart' else '')
            context = '[Autoresearch hook: ' + label + ']\n' + session.summary()['summary']
            receipt(session, payload, 'context_emitted')
            return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': context}}
        if not control.get('autoResume'):
            return {}
        runs = session.runs(state['config'])
        failures = 0
        for entry in reversed(runs):
            if entry['status'] not in ('discard', 'crash'):
                break
            failures += 1
        reason = None
        if state['remaining'] == 0:
            reason = 'Iteration budget exhausted'
        elif control.get('resumeTurns', 0) >= 200:
            reason = 'Automatic continuation reached 200 turns'
        elif failures > 20:
            reason = 'More than 20 consecutive discarded or crashed experiments'
        elif state['pending'] and state['pending']['phase'] in ('running', 'finalizing'):
            reason = 'Interrupted experiment requires recovery before automatic continuation'
        if reason:
            session.set_control(active=False, reason=reason)
            return {'systemMessage': 'Autoresearch stopped: ' + reason}
        if not runs:
            return {}  # Chat-only/setup turns must not loop forever.
        progress = str(runs[-1].get('id', runs[-1]['run']))
        if control.get('last_resume_progress') == progress:
            session.set_control(active=False, reason='No completed experiment since last automatic continuation')
            return {'systemMessage': 'Autoresearch paused because the last continuation made no experiment progress.'}
        session.set_control(resumeTurns=control.get('resumeTurns', 0) + 1, last_resume_progress=progress)
        return {'decision': 'block', 'reason': 'Continue the authorized autoresearch loop. Read .auto/prompt.md and run summary in ' + str(root) + '. Resolve any pending measured experiment, then test the next hypothesis. Honor user scope, budget, correctness checks, and stop requests.'}


def main():
    try:
        payload = json.load(sys.stdin)
        result = handle(payload)
    except (OSError, ValueError, KeyError) as exc:
        # A hook failure must never manufacture continuation or bypass a permission gate.
        result = {'systemMessage': 'Autoresearch hook skipped: ' + str(exc)}
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
