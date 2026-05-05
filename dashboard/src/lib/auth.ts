import { betterAuth } from "better-auth";
import { Pool } from "pg";

const DATABASE_URL = process.env.DATABASE_URL?.trim() ?? "";
const AUTH_SECRET = process.env.AUTH_SECRET?.trim() ?? "dev-insecure-secret-change-me-please";
const BETTER_AUTH_URL = process.env.BETTER_AUTH_URL?.trim() ?? "http://localhost:3000";

const pool = DATABASE_URL.length > 0 ? new Pool({ connectionString: DATABASE_URL }) : null;

export const auth = betterAuth({
  secret: AUTH_SECRET,
  baseURL: BETTER_AUTH_URL,
  ...(pool ? { database: pool } : {}),
  emailAndPassword: {
    enabled: true,
  },
  session: {
    expiresIn: 60 * 60 * 24 * 7,
  },
});

export type Auth = typeof auth;
