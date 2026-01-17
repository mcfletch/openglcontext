# OpenGLContext - Claude Code Guidelines

## Project Overview

OpenGLContext is a Python OpenGL framework providing a scenegraph-based rendering system with VRML97 compatibility.

## Project Plans

Project plans are stored in the `plans/` directory. The main index is [plans/PROJECT-PLAN.md](plans/PROJECT-PLAN.md), which contains a summary table of all plans with their status and links to individual plan documents.

When creating new plans:

1. Create a separate markdown file in `plans/` for detailed planning (e.g., `plans/FEATURE-NAME.md`)
2. Add an entry to the summary table in `plans/PROJECT-PLAN.md` with:
   - Link to the plan file
   - Current status (Planned, In Progress, Complete, etc.)
   - Brief description
3. Keep individual plan files focused on a single feature or initiative

## Code Conventions

- Tests are in the `tests/` directory
- Scenegraph nodes are in `OpenGLContext/scenegraph/`
- Rendering passes are in `OpenGLContext/passes/`
- Context implementations (GLUT, GLFW, etc.) are in `OpenGLContext/`

## Environment

Use the virtualenv at `../.env` for all Python operations:

```bash
source ../.env/bin/activate
```

Or run directly with:

```bash
../.env/bin/python <script.py>
```

## Testing

Run tests from the project root:

```bash
../.env/bin/python tests/<testname>.py
```

Many tests are interactive demos that display OpenGL content.
