# Nova Command Center - Current State

## Current Project
Nova Command Center — Railway to Render/Supabase migration

## Current Goal
Move Nova backend off Railway before billing starts (~15 days from 2026-07-15).

## Current Step
SUPABASE_URL and SUPABASE_SECRET_KEY added to Railway — confirmed healthy at /health. Render Web Service being created now (root dir: backend, env vars: DATABASE_URL, SUPABASE_URL, SUPABASE_SECRET_KEY, CORS_ORIGINS, GITHUB_PAT, ASSEMBLY_SECRET — all copied from Railway). AGNES_API_KEY and VITE_API_URL confirmed NOT needed on Render (backend code never reads them). Waiting on Render deploy to finish and produce a live URL.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history.
- Update this file whenever the project state changes.

## Last Updated
2026-07-15
