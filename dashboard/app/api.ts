import { SignalsResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchSignals(): Promise<SignalsResponse> {
  const res = await fetch(`${API_URL}/signals`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Signals fetch failed: ${res.status}`);
  }
  return res.json();
}