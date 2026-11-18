import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let vite;
let Spark;
before(async () => {
    vite = await createServer({
        logLevel: 'silent', server: { middlewareMode: true, hmr: false }, appType: 'custom',
    });
    ({ default: Spark } = await vite.ssrLoadModule('/src/components/Spark.jsx'));
});
after(async () => { await vite?.close(); });

function render(points) {
    return renderToStaticMarkup(createElement(Spark, { points, field: 'ph' }));
}

function point(minutes, segment) {
    return {
        recorded_at: new Date(Date.UTC(2025, 0, 1) + minutes * 60000).toISOString(),
        ph: 8, segment_ph: segment,
    };
}

test('downsampled time spacing does not introduce false gaps', () => {
    const html = render([point(0, 0), point(1, 0), point(2, 0), point(100, 0)]);
    assert.equal((html.match(/M\d/g) || []).length, 1);
    assert.equal((html.match(/L\d/g) || []).length, 3);
});

test('segment changes preserve gaps when missing rows are sampled out', () => {
    const html = render([point(0, 0), point(1, 0), point(2, 1), point(3, 1)]);
    assert.equal((html.match(/M\d/g) || []).length, 2);
});

test('raw readings retain the existing gap detection', () => {
    const html = render([point(0), point(1), point(2), point(100)]);
    assert.equal((html.match(/M\d/g) || []).length, 2);
});
