export interface ReadinessCheck {
  ok: boolean;
  error?: string;
}

export interface ReadinessResponse {
  status: "ok" | "degraded";
  checks: Record<string, ReadinessCheck>;
}
