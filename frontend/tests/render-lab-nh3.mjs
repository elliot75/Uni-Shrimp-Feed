import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { pathToFileURL } from 'node:url';

export async function renderLabRows(rows) {
    const vite = await createServer({
        logLevel: 'silent', server: { middlewareMode: true, hmr: false },
        appType: 'custom',
    });
    try {
        const { default: Cells } = await vite.ssrLoadModule('/src/components/LabNh3Cells.jsx');
        const { t } = await vite.ssrLoadModule('/src/i18n.js');
        return rows.map(({ row, locale = 'zh-TW' }) => renderToStaticMarkup(
            createElement('table', null, createElement('tbody', null,
                createElement('tr', null, createElement(Cells, { row, tr: key => t(locale, key) })))),
        ));
    } finally {
        await vite.close();
    }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    let input = '';
    for await (const chunk of process.stdin) input += chunk;
    process.stdout.write(JSON.stringify(await renderLabRows(JSON.parse(input))));
}
