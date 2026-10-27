import { Pool, type PoolClient } from 'pg';
const globalDb = globalThis as typeof globalThis & { omrPool?: Pool };
export function pool() {
  if (!process.env.DATABASE_URL) throw new Error('Database is not configured');
  const connection=new URL(process.env.DATABASE_URL);
  connection.searchParams.set('sslmode','verify-full');
  return globalDb.omrPool ??= new Pool({connectionString: connection.href,
    max: 3, connectionTimeoutMillis: 8000, idleTimeoutMillis: 10000});
}
export async function transaction<T>(fn: (db: PoolClient) => Promise<T>) {
  const db = await pool().connect();
  try { await db.query('BEGIN'); const result = await fn(db); await db.query('COMMIT'); return result; }
  catch (e) { await db.query('ROLLBACK'); throw e; }
  finally { db.release(); }
}
export class AppError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export function requireId(id: string) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new AppError(404, 'ไม่พบงานนี้');
  return id;
}
