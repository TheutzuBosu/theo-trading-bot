import { NextResponse } from "next/server";
import { makeSessionToken, SESSION_COOKIE, verifyPassword } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const password = typeof body.password === "string" ? body.password : "";

    if (!verifyPassword(password)) {
      return NextResponse.json(
        { error: "Parolă incorectă." },
        { status: 401 }
      );
    }

    const token = makeSessionToken(process.env.DASHBOARD_PASSWORD || "");
    const response = NextResponse.json({ ok: true });
    response.cookies.set(SESSION_COOKIE, token, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });
    return response;
  } catch {
    return NextResponse.json(
      { error: "Cerere invalidă." },
      { status: 400 }
    );
  }
}
