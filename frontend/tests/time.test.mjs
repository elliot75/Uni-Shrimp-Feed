import { test } from 'node:test';
import assert from 'node:assert/strict';
import { farmDateTimeInput, farmInputToIso, formatFarmTime } from '../src/utils/time.js';

test('Vietnam sampling times round trip across the date boundary', () => {
    const instant = new Date('2026-01-01T17:30:00Z');
    assert.equal(farmDateTimeInput(instant), '2026-01-02T00:30');
    assert.equal(farmInputToIso('2026-01-02T00:30'), instant.toISOString());
    assert.match(formatFarmTime(instant, 'vi'), /00:30/);
    assert.match(formatFarmTime(instant, 'zh-TW'), /00:30/);
    assert.equal(formatFarmTime(null), '—');
});
