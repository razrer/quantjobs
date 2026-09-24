// Run with: node --test tests/test_board_grouping.cjs
// Exercise the actual inline board code; no browser or third-party dependency.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
test('board data URL changes on each page load', () => {
  const loader = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map(m => m[1]).find(s => s.includes('document.write('));
  const requested = [];
  const context = vm.createContext({
    document: { write: html => requested.push(html) },
    Date: { now: () => 123456789 },
  });
  vm.runInContext(loader, context);
  assert.equal(requested[0], '<script src="data.js?v=123456789"></script>');
});
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).find(s => s.includes('function units('));
new vm.Script(script); // Syntax-check the complete application as well.
const start = script.indexOf('  const GROUP_KEY =');
const end = script.indexOf('\n  }', script.indexOf('  function units(')) + 4;
const context = vm.createContext({ state: { group: 'similar' } });
vm.runInContext(script.slice(start, end), context);
function group(jobs) {
  context.input = jobs;
  return vm.runInContext('units(input)', context);
}
const card = (id, extra = {}) => ({ id, firm: 'a.com', title: 'Researcher',
  loc: 'Hong Kong', ...extra });
const ids = units => units.flatMap(u => (u.list || [u.job]).map(j => j.id));

test('bundles two similar ads without losing either version or its metadata', () => {
  const jobs = [card('a', { fit: 'apply_now', due: '2026-10-01' }),
    card('b', { title: '  RESEARCHER ', fit: 'experienced' })];
  const units = group(jobs);
  assert.equal(units.length, 1);
  assert.equal(units[0].list[0], jobs[0]);
  assert.equal(units[0].list[1], jobs[1]);
  assert.deepEqual(Array.from(ids(units)), ['a', 'b']);
});
test('different employers, places and titles remain separate; missing places do not group', () => {
  const jobs = [card('a'), card('b', { firm: 'b.com' }),
    card('c', { loc: 'Singapore' }), card('d', { title: 'Senior Researcher' }),
    card('e', { loc: '' }), card('f', { loc: '' }),
    card('g', { loc: ' ' }), card('h', { loc: ' ' })];
  assert.equal(group(jobs).length, jobs.length);
});
test('a filtered-out version cannot become a representative of a matching version', () => {
  const jobs = [card('a', { fit: 'experienced' }), card('b', { fit: 'apply_now' })];
  const units = group(jobs.filter(j => j.fit === 'apply_now'));
  assert.equal(units[0].job.id, 'b');
});
test('stacking off restores individual cards in the supplied sort order', () => {
  context.state.group = '';
  assert.deepEqual(Array.from(ids(group([card('b'), card('a')]))), ['b', 'a']);
  context.state.group = 'similar';
});

test('verified aliases share a stack and filtering preserves the matching version', () => {
  const jobs = [card('a', { similar: 'a', fit: 'experienced' }),
    card('b', { similar: 'a', firm: 'alias.com', loc: 'Hong Kong SAR', fit: 'apply_now' })];
  assert.equal(group(jobs).length, 1);
  assert.deepEqual(Array.from(ids(group(jobs))), ['a', 'b']);
  assert.equal(group(jobs.filter(j => j.fit === 'apply_now'))[0].job.id, 'b');
});
