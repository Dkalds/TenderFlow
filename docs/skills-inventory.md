<!-- generado por scripts/gen_skills_inventory.py — no editar a mano -->

# Inventario de skills

Derivado de [`skills-lock.json`](../skills-lock.json) y el frontmatter de cada
`SKILL.md` en [`.agents/skills/`](../.agents/skills/). Regenerar con
`python scripts/gen_skills_inventory.py` tras instalar/actualizar un skill.
Ver AGENTS.md §7 para qué significa `trust`.

Total: 39 skills.

| Skill | Trust | Source | Descripción |
| --- | --- | --- | --- |
| `accessibility` | community | addyosmani/web-quality-skills | Audit and improve web accessibility following WCAG 2.2 guidelines. Use when asked to "improve accessibility", "a11y audit", "WCAG complia… |
| `animation-vocabulary` | community | emilkowalski/skill | Reverse-lookup glossary that turns a vague description of a web animation or motion effect into its exact term ("the bouncy thing when a… |
| `apple-design` | community | emilkowalski/skill | Apple's approach to interface design and fluid, physical motion, translated for the web. Use when building or reviewing gesture-driven UI… |
| `bash-defensive-patterns` | community | wshobson/agents | Master defensive Bash programming techniques for production-grade scripts. Use when writing robust shell scripts, CI/CD pipelines, or sys… |
| `emil-design-eng` | community | emilkowalski/skill | This skill encodes Emil Kowalski's philosophy on UI polish, component design, animation decisions, and the invisible details that make so… |
| `fastapi-python` | community | mindrally/skills | Expert in FastAPI Python development with best practices for APIs and async operations |
| `fastapi-templates` | community | wshobson/agents | Create production-ready FastAPI projects with async patterns, dependency injection, and comprehensive error handling. Use when building n… |
| `find-animation-opportunities` | community | emilkowalski/skill | Search a codebase or UI for places that don't animate but should, and reject everything that shouldn't. Read-only; it proposes motion wit… |
| `improve-animations` | community | emilkowalski/skill | Survey a codebase's animation and motion code as a senior motion advisor, then produce a prioritized audit and self-contained implementat… |
| `machine-learning` | community | pluginagentmarketplace/custom-plugin-python | Python machine learning with scikit-learn, PyTorch, and TensorFlow |
| `nodejs-backend-patterns` | community | wshobson/agents | Build production-ready Node.js backend services with Express/Fastify, implementing middleware patterns, error handling, authentication, d… |
| `nodejs-best-practices` | community | sickn33/antigravity-awesome-skills | Node.js development principles and decision-making. Framework selection, async patterns, security, and architecture. Teaches thinking, no… |
| `pandas-data-analysis` | community | pluginagentmarketplace/custom-plugin-python | Master data manipulation, analysis, and visualization with Pandas, NumPy, and Matplotlib |
| `pandas-pro` | community | jeffallan/claude-skills | Performs pandas DataFrame operations for data analysis, manipulation, and transformation. Use when working with pandas DataFrames, data c… |
| `pick-ui-library` | community | emilkowalski/skill | Pick the right library for a given frontend task from a curated, opinionated list — numbers, OTP inputs, charts, command menus, virtualiz… |
| `pydantic` | community | bobmatnyc/claude-mpm-skills | Python data validation using type hints and runtime type checking with Pydantic v2's Rust-powered core for high-performance validation in… |
| `python-executor` | community | inferen-sh/skills | Execute Python code in a safe sandboxed environment via [inference.sh](https://inference.sh). Pre-installed: NumPy, Pandas, Matplotlib, r… |
| `python-patterns` | community | affaan-m/everything-claude-code | Pythonic idioms, PEP 8 standards, type hints, and best practices for building robust, efficient, and maintainable Python applications. |
| `python-testing-patterns` | community | wshobson/agents | Implement comprehensive testing strategies with pytest, fixtures, mocking, and test-driven development. Use when writing Python tests, se… |
| `review-animations` | community | emilkowalski/skill | Reviews animation and motion code against a high craft bar derived from Emil Kowalski's design engineering philosophy. Default to flaggin… |
| `scikit-learn` | community | davila7/claude-code-templates | Machine learning in Python with scikit-learn. Use when working with supervised learning (classification, regression), unsupervised learni… |
| `senior-data-scientist` | community | davila7/claude-code-templates | World-class data science skill for statistical modeling, experimentation, causal inference, and advanced analytics. Expertise in Python (… |
| `seo` | community | addyosmani/web-quality-skills | Optimize for search engine visibility and ranking. Use when asked to "improve SEO", "optimize for search", "fix meta tags", "add structur… |
| `sqlalchemy` | community | bobmatnyc/claude-mpm-skills | SQLAlchemy Python SQL toolkit and ORM with powerful query builder, relationship mapping, and database migrations via Alembic |
| `sqlalchemy-alembic-expert-best-practices-code-review` | community | wispbit-ai/skills | SQLAlchemy ORM and Alembic migration best practices for building safe, performant database schemas. This skill should be used when writin… |
| `ui-ux-pro-max` | community | nextlevelbuilder/ui-ux-pro-max-skill | UI/UX design intelligence for web and mobile. Includes 50+ styles, 161 color palettes, 57 font pairings, 161 product types, 99 UX guideli… |
| `agent-browser` | first-party | vercel-labs/agent-browser | Browser automation CLI for AI agents. Use when the user needs to interact with websites, including navigating pages, filling forms, click… |
| `deploy-to-vercel` | first-party | vercel-labs/agent-skills | Deploy applications and websites to Vercel. Use when the user requests deployment actions like "deploy my app", "deploy and give me the l… |
| `find-skills` | first-party | vercel-labs/skills | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that… |
| `frontend-design` | first-party | anthropics/skills | Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web compone… |
| `supabase` | first-party | supabase/agent-skills | Use when doing ANY task involving Supabase. Triggers: Supabase products (Database, Auth, Edge Functions, Realtime, Storage, Vectors, Cron… |
| `supabase-postgres-best-practices` | first-party | supabase/agent-skills | Postgres performance optimization and best practices from Supabase. Use this skill when writing, reviewing, or optimizing Postgres querie… |
| `upstash` | first-party | upstash/skills | Work with any Upstash TypeScript/JavaScript SDK including Redis, Box, QStash, Workflow, Vector, Search and Ratelimit. Use when the user i… |
| `upstash-cli` | first-party | upstash/skills | Run the Upstash CLI (`upstash`) against the Upstash Developer API for Redis, Vector, Search, QStash, and teams. Use when listing or manag… |
| `upstash-ratelimit-js` | first-party | upstash/skills | Lightweight guidance for using the Upstash Redis RateLimit TypeScript/JavaScript SDK, including setup steps, basic usage, and pointers to… |
| `upstash-redis-js` | first-party | upstash/skills | Work with the Upstash Redis TypeScript/JavaScript SDK for serverless Redis operations. Use for caching, session storage, rate limiting, l… |
| `vercel-composition-patterns` | first-party | vercel-labs/agent-skills | React composition patterns that scale. Use when refactoring components with |
| `vercel-react-best-practices` | first-party | vercel-labs/agent-skills | React and Next.js performance optimization guidelines from Vercel Engineering. This skill should be used when writing, reviewing, or refa… |
| `web-design-guidelines` | first-party | vercel-labs/agent-skills | Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review… |
