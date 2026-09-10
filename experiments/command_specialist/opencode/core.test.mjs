import test from 'node:test'
import assert from 'node:assert/strict'
import { selectedEvidence, textPage } from './index.mjs'

test('selection preserves bytes and translates page indices to file lines', () => {
  const lines = ['routine', "ERROR: café [draft]'s file_1 {{build}}", '', 'SUMMARY: failed\u2028verbatim']
  const result = selectedEvidence(lines, [2, 3, 4], 21)
  assert.deepEqual(result, { evidence: lines.slice(1), source_lines: [22, 23, 24] })
})

test('invalid selections cannot fabricate or duplicate evidence', () => {
  for (const indices of [[0], [3], [1, 1], [2, 1], [true], [1.5], ['1'], null]) {
    assert.throws(() => selectedEvidence(['one', 'two'], indices, 1))
  }
})

test('unsupported or shortened native output cannot become exact evidence', () => {
  assert.throws(() => textPage({ output: { type: 'list-page', entries: [] } }))
  assert.throws(() => textPage({ output: { type: 'text-page', content: 'value... (line truncated to 2000 chars)', offset: 1, truncated: false } }))
  assert.deepEqual(textPage({ output: { type: 'text-page', content: 'one\n\nthree\u2028same line', offset: 9, truncated: true, next: 12 } }),
    { lines: ['one', '', 'three\u2028same line'], offset: 9, truncated: true, next: 12 })
})
