import {test} from 'node:test';
import assert from 'node:assert/strict';
import {extract} from './extract.mjs';

test('recovers escaped literal commands and preserves source spans', () => {
  const code = 'text(await tools.exec_command({cmd:"Get-Content \'a.txt\' -Head 2\\n",workdir:cwd}));';
  const result = extract(code);
  assert.equal(result.candidates.length, 1);
  const row = result.candidates[0];
  assert.equal(row.command, "Get-Content 'a.txt' -Head 2\n");
  assert.deepEqual(row.dynamic_fields, ['workdir']);
  assert.equal(code.slice(row.span.start, row.span.end), 'tools.exec_command({cmd:"Get-Content \'a.txt\' -Head 2\\n",workdir:cwd})');
});
test('comments, quoted examples and regexes do not become calls', () => {
  const r = extract('// tools.exec_command({cmd:"bad"})\nconst s = "tools.exec_command({cmd:1})"; const re=/tools.exec_command/;');
  assert.equal(r.candidates.length, 0);
});
test('dynamic commands, spreads, getters and overridden literals abstain', () => {
  for (const args of ['{cmd:build()}', '{cmd:`read ${name}`}', '{cmd:"x",...rest}',
    '{get cmd(){return "x"}}', '{[key]:"x",cmd:"y"}', '{cmd:"x",cmd:dynamic}']) {
    const r = extract(`await tools.exec_command(${args});`);
    assert.equal(r.candidates.length, 0, args);
    assert.equal(r.rejected.length, 1, args);
  }
});
test('unexecuted branches and function bodies stay candidates without running code', () => {
  globalThis.commandParserSentinel = false;
  const r = extract('globalThis.commandParserSentinel=true; if(false){tools.exec_command({cmd:"x"})}; function unused(){tools.shell({command:["pwsh","-c","y"]})}');
  assert.equal(globalThis.commandParserSentinel, false);
  assert.equal(r.candidates.length, 2);
  assert.ok(r.candidates.every(x => x.control_context.length && !x.execution_observed));
});
test('literal concatenation and no-expression templates work without evaluation', () => {
  const r = extract('await tools.exec_command({cmd:`Get-Content x`+" -Tail 4"});');
  assert.equal(r.candidates[0].command, 'Get-Content x -Tail 4');
  assert.equal(extract('tools.exec_command({cmd:"x"+variable})').candidates.length, 0);
});
test('bad and oversized inputs have explicit dispositions', () => {
  assert.equal(extract('await (').status, 'parse_error');
  assert.equal(extract('x'.repeat(2_000_001)).status, 'oversized_input');
  assert.equal(extract(null).status, 'invalid_input');
});
