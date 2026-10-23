// Embedded PostgreSQL for tests only: no server, socket, credentials or disk data.
import { PGlite } from '@electric-sql/pglite';
import { createInterface } from 'node:readline';

const db = new PGlite();
const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
    try {
        const { sql, params, casts } = JSON.parse(line);
        let index = 0;
        const result = await db.query(sql.replace(/%s/g, () => `$${++index}${casts[index - 1]}`), params);
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } catch (error) {
        process.stdout.write(`${JSON.stringify({ error: error.message })}\n`);
    }
}
await db.close();
