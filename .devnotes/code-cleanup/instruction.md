# Codebase Cleanup & Deprecation Removal

You are acting as a senior software engineer responsible for reducing technical debt while preserving existing functionality.

Your objective is to identify and remove deprecated, obsolete, unused, or superseded code throughout the entire repository.

## Primary Goal

Leave the codebase in a cleaner, smaller, and more maintainable state without changing the application's external behavior.

Only remove code that is no longer used or has been replaced by newer implementations.

---

# Phase 1 — Understand the Project

Before making any modifications:

1. Read the repository structure.
2. Understand the overall architecture.
3. Identify:

   * Current production execution paths
   * Active modules
   * Experimental modules
   * Legacy implementations
   * Feature flags
   * Build system
   * Packaging process
   * Deployment process
   * Docker services
   * CI/CD configuration
4. Determine which code paths are actually used.

Do not assume anything is unused simply because it appears old.

---

# Phase 2 — Build a Dependency Graph

Create a complete dependency map of:

* Internal modules
* Package imports
* Dynamic imports
* Reflection
* Plugin loading
* Configuration loading
* Environment variable usage
* Entry points
* Scripts
* CLI tools
* Services
* Docker compose services
* Background workers
* Scheduled jobs

Identify what is actually referenced.

---

# Phase 3 — Detect Deprecated Components

Find components that have become obsolete, including:

## Deprecated Features

* Features disabled by configuration
* Feature flags permanently off
* Replaced workflows
* Old APIs
* Legacy endpoints
* Old UI components
* Previous implementations replaced by newer architecture

---

## Deprecated Models

Find model implementations that are no longer used.

Examples include:

* old LLM providers
* retired embedding models
* unused rerankers
* legacy TTS engines
* obsolete STT implementations
* experimental models never referenced
* duplicated inference wrappers

Remove associated:

* loaders
* wrappers
* configuration
* helper utilities
* tests (if obsolete)

---

## Deprecated Packages

Find packages that are no longer required.

Examples:

* requirements.txt
* pyproject.toml
* package.json
* poetry.lock
* uv.lock
* pip-tools
* conda
* Docker images

Remove packages that have no remaining usage.

---

## Deprecated Dependencies

Remove:

* transitive dependencies no longer needed
* optional packages no longer referenced
* compatibility shims
* migration helpers
* version workarounds
* temporary fixes

---

## Deprecated Imports

Remove:

* unused imports
* dead imports
* compatibility imports
* fallback imports
* duplicate imports
* wildcard imports that are unnecessary

Ensure formatting tools remain satisfied.

---

## Dead Code

Remove:

* unreachable code
* never-called functions
* unused methods
* unused classes
* unused constants
* unused enums
* unused dataclasses
* unused interfaces
* obsolete utility functions
* abandoned helper modules

---

## Dead Files

Remove files that are no longer referenced, including:

* legacy modules
* duplicate implementations
* abandoned experiments
* old migration scripts
* archived code
* obsolete adapters
* deprecated service implementations
* unused utilities

Only remove files after confirming there are no references.

---

## Dead Assets

Remove:

* unused images
* icons
* fonts
* sample data
* example configs
* obsolete prompts
* unused templates
* duplicate documentation
* unused model configs

---

## Docker Cleanup

Identify and remove:

* unused Dockerfiles
* unused compose services
* obsolete containers
* deprecated volumes
* unused build stages
* unused images
* unused health checks

---

## Configuration Cleanup

Remove obsolete configuration entries from:

* .env.example
* config files
* YAML
* JSON
* TOML
* Docker Compose
* Kubernetes manifests
* nginx configs

Do not remove active configuration.

---

## Build System Cleanup

Remove obsolete:

* build scripts
* npm scripts
* Makefile targets
* shell scripts
* helper scripts
* installation scripts

---

## Test Cleanup

Remove tests that only verify removed functionality.

Do not reduce coverage for active features.

---

# Phase 4 — Verify Usage Before Removal

Before deleting anything, verify using multiple methods where applicable:

* static references
* import graph
* call graph
* search across repository
* configuration references
* runtime entry points
* Docker references
* build scripts
* CI workflows
* packaging scripts
* documentation references

If uncertain, retain the code and report it instead of deleting it.

Never remove code based solely on naming or age.

---

# Phase 5 — Refactor After Removal

After cleanup:

* remove empty directories
* simplify conditional logic
* remove obsolete comments
* remove TODOs tied to deleted code
* consolidate duplicated utilities if appropriate
* update imports
* reorder imports
* update type hints
* run formatting where applicable

Do not perform unrelated refactoring.

---

# Phase 6 — Update Dependencies

After cleanup:

* regenerate lock files
* remove unused dependencies
* verify dependency graphs
* ensure reproducible builds
* remove orphaned package references

---

# Phase 7 — Validation

Ensure:

* project builds successfully
* application starts
* tests pass
* lint passes
* formatting passes
* type checking passes (if applicable)

Resolve issues introduced by cleanup.

---

# Deliverables

Produce a cleanup report including:

## Executive Summary

* Files removed
* Lines removed
* Packages removed
* Dependencies removed
* Imports removed
* Dead code removed
* Configuration cleaned
* Docker cleanup
* Documentation updated

---

## Detailed Report

For every removed item include:

* file path
* reason for removal
* evidence that it was unused
* replacement (if any)

---

## Potential Manual Review

List anything that appears deprecated but could not be safely removed, including why manual review is recommended.

---

# Safety Rules

* Never remove active production code.
* Never remove dynamically loaded code unless verified.
* Never remove reflection-based modules without confirmation.
* Never remove plugin implementations unless confirmed unused.
* Never remove public APIs that remain in use.
* Never remove code solely because it appears old.
* Prefer preserving uncertain code over deleting it.
* Keep changes focused strictly on cleanup and deprecation removal.
