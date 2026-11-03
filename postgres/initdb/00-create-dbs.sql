-- Runs once on first start of the postgres volume.
-- litellm: LiteLLM virtual keys, budgets, spend logs (prisma-managed schema)
-- fundraising : system of record (tenants, users, donors, donations, transactions, ai_registry)
-- kb     : pgvector knowledge base with tenant metadata
CREATE DATABASE litellm;
CREATE DATABASE fundraising;
CREATE DATABASE kb;
\connect kb
CREATE EXTENSION IF NOT EXISTS vector;
