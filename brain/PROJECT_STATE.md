# Nova Command Center - Current State

## Current Project
Nova Command Center — Railway to Render/Supabase migration

## Current Goal
Move Nova backend off Railway before billing starts (~15 days from 2026-07-15).

## Current Step
Waiting on SUPABASE_URL and SUPABASE_SECRET_KEY being added to Railway's Variables tab (fixes a live upload bug AND unblocks the Render move). After that: create Render Web Service, set env vars, get the new URL, rewrite 5 workflow files that hardcode the old Railway URL.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history.
- Update this file whenever the project state changes.

## Last Updated
2026-07-15
