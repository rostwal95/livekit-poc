/** Owner v9 statement order over a synthetic client; actual DDL lives in pg_result_receiver_cases. */
import { beforeEach, expect, it, vi } from 'vitest';
const owner = vi.hoisted(() => ({ steps: [] as string[], version: 8 }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => {
      owner.steps.push('validate');
      return original.DEFAULT_LIMITS;
    },
    catalog: async () => ({}),
    PgClient: class {
      on() {}
      async connect() {}
      async query(text: string) {
        owner.steps.push(text);
        return text.startsWith('SELECT version FROM')
          ? { rows: [{ version: owner.version }], rowCount: 1 }
          : { rows: [], rowCount: 0 };
      }
      async end() {}
    },
  };
});
import { upgradeChannelSchemaV9 } from '../src/migrations.js';
const DB = {
  host: '127.0.0.1',
  port: 15432,
  database: 'livekit_lab',
  user: 'continuity_migrator',
  password: 'synthetic'.repeat(5),
  schema: 'p2_index_upgrade_unit',
};
const LOCK = `LOCK TABLE ${['schema_metadata', 'admission', 'processing_intents', 'send_attempts', 'send_recovery_commands'].map((name) => `"${DB.schema}"."${name}"`).join(',')} IN ACCESS EXCLUSIVE MODE`;
beforeEach(() => {
  owner.steps.length = 0;
});
it.each([8, 9])(
  'locks the indexed tables and revalidates before any v9 DDL from version %i',
  async (version) => {
    owner.version = version;
    await upgradeChannelSchemaV9(DB);
    const read = owner.steps.findIndex((step) => step.startsWith('SELECT version FROM')),
      lock = owner.steps.indexOf(LOCK),
      ddl = owner.steps.findIndex((step) => /CREATE INDEX|ALTER TABLE|SET version=9/.test(step));
    expect(read).toBeGreaterThan(0);
    expect(lock).toBeGreaterThan(read);
    expect(owner.steps[lock + 1]).toBe('validate');
    if (version === 8) expect(ddl).toBeGreaterThan(lock + 1);
    else expect(ddl).toBe(-1);
    expect(owner.steps.filter((step) => step.includes('CREATE INDEX'))).toHaveLength(
      version === 8 ? 1 : 0,
    );
    expect(owner.steps.at(-1)).toBe('COMMIT');
  },
);
