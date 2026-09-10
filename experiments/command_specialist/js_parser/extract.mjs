import {parse} from 'acorn';
import {createInterface} from 'node:readline';
import {pathToFileURL} from 'node:url';

const unknown = Symbol('not a static value');
const commands = new Set(['exec_command', 'shell_command', 'shell', 'bash', 'powershell',
  'run_terminal_cmd', 'run_terminal_command', 'run_shell_command', 'oc_bash']);

function literal(node, depth = 0) {
  if (!node || depth > 40) return unknown;
  if (node.type === 'Literal' && !node.regex && !node.bigint) return node.value;
  if (node.type === 'TemplateLiteral' && !node.expressions.length) {
    return node.quasis.map(q => q.value.cooked).join('');
  }
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    const a = literal(node.left, depth + 1), b = literal(node.right, depth + 1);
    return typeof a === 'string' && typeof b === 'string' ? a + b : unknown;
  }
  if (node.type === 'ArrayExpression') {
    const values = node.elements.map(x => literal(x, depth + 1));
    return values.includes(unknown) ? unknown : values;
  }
  if (node.type === 'ObjectExpression') {
    const result = Object.create(null);
    for (const property of node.properties) {
      const key = propertyKey(property);
      if (key === unknown) return unknown;
      const value = literal(property.value, depth + 1);
      if (value === unknown) return unknown;
      result[key] = value;
    }
    return result;
  }
  return unknown;
}

function propertyKey(property) {
  if (property.type !== 'Property' || property.kind !== 'init' || property.method || property.computed) return unknown;
  if (property.key.type === 'Identifier') return property.key.name;
  if (property.key.type === 'Literal' && typeof property.key.value === 'string') return property.key.value;
  return unknown;
}

function toolName(node) {
  if (node?.type !== 'MemberExpression' || node.object.type !== 'Identifier' ||
      !['tools', 'functions'].includes(node.object.name)) return null;
  const name = node.computed ? literal(node.property) : node.property.name;
  return typeof name === 'string' && commands.has(name.split('__').at(-1)) ? name : null;
}

export function extract(code) {
  if (typeof code !== 'string') return {status: 'invalid_input', candidates: [], rejected: []};
  if (Buffer.byteLength(code) > 2_000_000) return {status: 'oversized_input', candidates: [], rejected: []};
  let tree;
  try {
    tree = parse(code, {ecmaVersion: 2025, sourceType: 'module', locations: true,
      allowReturnOutsideFunction: true, allowAwaitOutsideFunction: true});
  } catch (error) {
    return {status: 'parse_error', error_position: error.pos ?? null, candidates: [], rejected: []};
  }
  const candidates = [], rejected = [];
  const stack = [[tree, []]];
  while (stack.length) {
    const [node, ancestors] = stack.pop();
    const tool = node.type === 'CallExpression' ? toolName(node.callee) : null;
    if (tool) {
      const span = {start: node.start, end: node.end, line: node.loc.start.line, column: node.loc.start.column};
      const argument = node.arguments[0];
      const values = Object.create(null), dynamic_fields = [];
      let reason = node.arguments.length !== 1 || argument?.type !== 'ObjectExpression' ? 'non_literal_argument_object' : null;
      if (!reason) {
        for (const property of argument.properties) {
          const key = propertyKey(property);
          if (key === unknown) { reason = 'spread_computed_or_accessor_property'; break; }
          const value = literal(property.value);
          // Later duplicate keys override earlier ones, including dynamic values.
          values[key] = value;
        }
        for (const key of Object.keys(values)) if (values[key] === unknown) dynamic_fields.push(key);
      }
      const commandKey = ['cmd', 'command', 'command_line'].find(k => Object.hasOwn(values, k));
      const command = values[commandKey];
      if (!reason && !(typeof command === 'string' || Array.isArray(command) && command.length && command.every(x => typeof x === 'string'))) {
        reason = 'missing_or_dynamic_command';
      }
      if (reason) rejected.push({tool, span, reason});
      else {
        const static_arguments = Object.fromEntries(Object.entries(values).filter(([,v]) => v !== unknown));
        const control_context = [...new Set(ancestors.filter(t => /Function|IfStatement|ConditionalExpression|For|While|LogicalExpression|Switch|TryStatement/.test(t)))];
        candidates.push({tool, command, static_arguments, dynamic_fields, span, control_context,
          execution_observed: false, task_correctness: 'abstain'});
      }
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'loc') continue;
      if (Array.isArray(value)) {
        for (let i = value.length - 1; i >= 0; --i) if (value[i]?.type) stack.push([value[i], [...ancestors, node.type]]);
      } else if (value?.type) stack.push([value, [...ancestors, node.type]]);
    }
  }
  candidates.sort((a,b) => a.span.start - b.span.start);
  rejected.sort((a,b) => a.span.start - b.span.start);
  return {status: 'parsed', candidates, rejected, span_units: 'UTF-16 offsets in original code'};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({input: process.stdin, crlfDelay: Infinity})) {
    try {
      const row = JSON.parse(line);
      process.stdout.write(JSON.stringify({id: row.id, ...extract(row.code)}) + '\n');
    } catch {
      process.stdout.write(JSON.stringify({id: null, status: 'invalid_json', candidates: [], rejected: []}) + '\n');
    }
  }
}
