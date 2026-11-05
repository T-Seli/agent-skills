"""PreToolUse gate: deny an agent's bare test-suite command so every suite goes through test-slot."""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

PACKAGE_RUNNERS = {'npm', 'pnpm', 'yarn', 'bun'}
OPTIONS_WITH_VALUE = {'--prefix', '-C', '--dir', '--cwd', '--filter', '-w', '--workspace'}
WRAPPERS = {'env', 'time', 'nice', 'command', 'exec'}
NPX = {'npx', 'pnpx', 'bunx'}
TEST_TOOLS = {'vitest', 'jest', 'mocha', 'pytest', 'playwright'}


def _words(tokens):
    """Tokens that are not options, skipping the values of options that take one."""
    skip = False
    for token in tokens:
        if skip:
            skip = False
        elif token in OPTIONS_WITH_VALUE:
            skip = True
        elif not token.startswith('-'):
            yield token


def _runs_tests(tokens):
    while tokens and (tokens[0] in WRAPPERS or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', tokens[0])):
        tokens = tokens[1:]
    if not tokens:
        return False
    tool, rest = Path(tokens[0]).name, tokens[1:]
    words = list(_words(rest))
    if tool in PACKAGE_RUNNERS:
        if words[:1] in (['test'], ['t'], ['tst']):
            return True
        return words[:1] in (['run'], ['run-script']) and len(words) > 1 and words[1].startswith('test')
    if tool == 'node':
        return '--test' in rest
    if tool in NPX:
        return bool(words) and words[0] in TEST_TOOLS
    if tool in TEST_TOOLS:
        return True
    if re.fullmatch(r'python[0-9.]*', tool):
        return rest[:1] == ['-m'] and rest[1:2] in (['pytest'], ['unittest'])
    if tool in ('go', 'cargo', 'make'):
        return words[:1] == ['test']
    return False


def runs_tests(command):
    for segment in re.split(r'&&|\|\||[;|\n]', command):
        try:
            tokens = shlex.split(segment)
        except ValueError:  # an unbalanced quote across segments; judge the next one
            continue
        if _runs_tests(tokens):
            return True
    return False


def project_slots_itself(cwd):
    """The project's CLAUDE.md says its runner takes the slots (§ Run & test `Test slot`: `runner`)."""
    top = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if top.returncode != 0:
        return False
    claude = Path(top.stdout.strip()) / 'CLAUDE.md'
    text = claude.read_text(encoding='utf-8') if claude.is_file() else ''
    match = re.search(r'^- Test slot: *`([^`]*)`', text, re.M)
    return bool(match) and match.group(1) == 'runner'


def decide(event, cli):
    """A deny reason for a bare test-suite command, else None."""
    if event.get('tool_name') != 'Bash':
        return None
    command = event.get('tool_input', {}).get('command', '')
    if 'test-slot' in command or not runs_tests(command) or project_slots_itself(event.get('cwd') or '.'):
        return None
    return ('Test suites go through the machine-wide test limit, so parallel sessions cannot exhaust memory. '
            f'Run instead:\n{shlex.quote(cli)} test-slot {shlex.quote(command)}\n'
            'Add --weight 2 when the command runs two suites at once. Exit 75 means busy or memory short after the '
            'wait, not a test failure. If the project runner slots each suite itself, set '
            '"- Test slot: `runner`" in its CLAUDE.md § Run & test.')


def main(cli):
    reason = decide(json.load(sys.stdin), cli)
    if reason:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                 'permissionDecisionReason': reason}}))
    return 0
