import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export async function POST() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Neautorizat." }, { status: 401 });
  }
  return NextResponse.json(
    {
      ok: false,
      message: "Butonul KILL se conectează în etapa B6 (procesul live pe demo).",
    },
    { status: 501 }
  );
}
