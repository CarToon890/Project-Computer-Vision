import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
export function hashPassword(password) {
  if (typeof password !== 'string' || password.length < 12 || password.length > 256) throw Error('Use 12–256 characters');
  const salt = randomBytes(16).toString('hex');
  return `scrypt$${salt}$${scryptSync(password, salt, 64, {N:32768, r:8, p:1, maxmem:64*1024*1024}).toString('hex')}`;
}
export function verifyPassword(password, stored) {
  const [kind, salt, expected] = (stored || '').split('$');
  if (kind !== 'scrypt' || !/^[a-f0-9]{32}$/.test(salt || '') || !/^[a-f0-9]{128}$/.test(expected || '')) return false;
  if (typeof password !== 'string' || password.length > 256) return false;
  const actual = scryptSync(password, salt, 64, {N:32768, r:8, p:1, maxmem:64*1024*1024});
  return timingSafeEqual(actual, Buffer.from(expected, 'hex'));
}
