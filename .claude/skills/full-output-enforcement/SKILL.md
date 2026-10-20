---
name: full-output-enforcement
description: Deliver every requested deliverable complete, with no placeholder code, and split very long output at a clean boundary. Use when the user asks for full, unabridged files or a fixed number of deliverables.
disable-model-invocation: true
---

# Full-Output Enforcement

When the user asks for a full file, N components or an unabridged answer, deliver all of it. Write the actual code and content for every part requested; don't stand in for omitted parts with comments such as `// ...` or `// rest of code`, ellipses, a skeleton, or an offer to continue.

If the work can't fit in one reply, write the long parts to files, or stop at a clean boundary (end of a file, function or section) and say exactly what remains.
