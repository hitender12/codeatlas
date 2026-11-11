// Authentication helpers for the shop (TypeScript).
import * as crypto from "crypto";

export function hashPassword(password: string): string {
  return crypto.createHash("sha256").update(password).digest("hex");
}

export function verifyToken(token: string, expected: string): boolean {
  return token === expected;
}

export function createSession(username: string) {
  return { username, token: Math.random().toString(36).slice(2) };
}

export class Authenticator {
  constructor(private users: Record<string, string>) {}

  authenticate(username: string, password: string) {
    const stored = this.users[username];
    if (!stored) return false;
    return verifyToken(hashPassword(password), stored);
  }

  login(username: string, password: string) {
    if (!this.authenticate(username, password)) return null;
    return createSession(username);
  }

  logout(session: { expiresAt: number }) {
    session.expiresAt = 0;
    return session;
  }
}
