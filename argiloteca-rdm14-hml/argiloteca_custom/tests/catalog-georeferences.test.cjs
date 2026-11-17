const { test } = require('node:test');
const assert = require('node:assert/strict');
const { summarizePoints, filterMineralPoints } = require('../argiloteca/static/js/argiloteca-catalog.js');
const minerals = [
  { slug: 'kaolinite', names: ['kaolinite', 'Caulinita'] },
  { slug: 'illite-smectite', names: ['illite-smectite', 'Ilita/Esmectita'] }
];
const point = { record_id: 'r1', lat: -30.8, lon: -54, argilominerais: ['Caulinita'], title: 'Estudo', sample_location: 'Local do estudo' };

test('deduplicates grouped markers and aliases without losing distinct coordinates', () => {
  const result = summarizePoints([point, point, {...point, argilominerais: ['Kaolinite', 'Caulinita']}, {...point, lon: -53}], minerals);
  assert.equal(result.records, 1);
  assert.equal(result.points, 2);
  assert.equal(result.summaries.get('kaolinite').records.size, 1);
  assert.equal(result.summaries.get('kaolinite').points.size, 2);
});

test('excludes missing, infinite and out-of-range coordinates but accepts zero', () => {
  const result = summarizePoints([null, '', ' ', 91, Infinity].map(lat => ({...point, lat})).concat(
    {...point, lon: 181}, {...point, record_id: '', lat: 0}, {...point, lat: 0, lon: 0}
  ), minerals);
  assert.equal(result.points, 1);
  assert.equal(result.summaries.get('kaolinite').points.values().next().value.latitude, 0);
});

test('matches Portuguese, accents and mixed mineral names without matching parent groups', () => {
  const result = summarizePoints([
    {...point, argilominerais: ['ILÍTA/ESMECTITA']},
    {...point, record_id: 'r2', argilominerais: ['Grupo da caulinita', 'Caulinita extra']}
  ], minerals);
  assert.equal(result.summaries.get('illite-smectite').records.size, 1);
  assert.equal(result.summaries.get('kaolinite').records.size, 0);
});

test('supports raw mineral points and preserves source metadata', () => {
  const result = summarizePoints([{...point, argilominerais: undefined, kind: 'argilomineral', label: 'Caulinita', latitude: '-30,9', dataset_source: 'PANGAEA'}], minerals);
  const row = result.summaries.get('kaolinite').points.values().next().value;
  assert.deepEqual(row, { record: 'r1', latitude: -30.9, longitude: -54, title: 'Estudo', location: 'Local do estudo', source: 'PANGAEA' });
});

test('keeps different records at the same coordinate separate', () => {
  const result = summarizePoints([point, {...point, record_id: 'r2'}], minerals);
  assert.equal(result.summaries.get('kaolinite').records.size, 2);
  assert.equal(result.summaries.get('kaolinite').points.size, 2);
});

test('empty data yields explicit zero counts for every mineral', () => {
  const result = summarizePoints([], minerals);
  assert.equal(result.records, 0);
  assert.equal(result.points, 0);
  assert.equal(result.summaries.size, 2);
  assert.equal(result.summaries.get('kaolinite').points.size, 0);
});

test('map and catalog use the same explicit association instead of substring search', () => {
  const data = [point, {...point, record_id: 'mixed', argilominerais: ['Caulinita/Esmectita']}];
  const visible = filterMineralPoints(data, minerals[0].names);
  assert.deepEqual(visible, [point]);
  assert.equal(visible.length, summarizePoints(data, minerals).summaries.get('kaolinite').points.size);
});
