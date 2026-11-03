import crypto from "crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "theo_dash_session";

function getExpectedPassword(): string {
  return process.env.DASHBOARD_PASSWORD || "";
}

export function makeSessionToken(password: string): string {
  return crypto
    .createHmac("sha256", "theo-trading-bot-dashboard-v1")
    .update(password)
    .digest("hex");
}

export function verifyPassword(input: string): boolean {
  const expected = getExpectedPassword();
  if (!expected) {
    return false;
  }
  const a = Buffer.from(makeSessionToken(input), "utf8");
  const b = Buffer.from(makeSessionToken(expected), "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export async function isAuthenticated(): Promise<boolean> {
  const expected = getExpectedPassword();
  if (!expected) {
    return false;
  }
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value || "";
  const validToken = makeSessionToken(expected);
  const a = Buffer.from(token, "utf8");
  const b = Buffer.from(validToken, "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
