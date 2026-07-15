# Nova Command Center - Current State

## Current Project
Nova Command Center — Railway to Render/Supabase migration

## Current Goal
Move Nova backend off Railway before billing starts (~15 days from 2026-07-15).

## Current Step
Render Web Service live and healthy: https://novacommandcenter.onrender.com/health confirmed "healthy". Env vars set on Render: DATABASE_URL, SUPABASE_URL, SUPABASE_SECRET_KEY, CORS_ORIGINS, GITHUB_PAT, ASSEMBLY_SECRET, PORT=8000. Free instance type. Next: rewrite hardcoded Railway URL in 5 workflow yml files, update youtube_upload.yml RAILWAY_URL secret, verify full pipeline run, then decommission Railway.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history.
- Update this file whenever the project state changes.

## Last Updated
2026-07-15
