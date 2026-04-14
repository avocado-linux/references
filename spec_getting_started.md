# getting_started.md Specification

The getting started guide is the detailed companion to the README. It walks a user through everything they need to go from zero to a running system using this reference.

## Structure

The getting started guide should follow this structure:

```markdown
# <img src="icon.png" width="32" height="32" style="vertical-align: middle;" /> Getting Started with <Reference Name>

## Prerequisites

- List all required hardware, software, and tools
- Link to Avocado CLI installation if relevant
- Note any target-specific requirements

## Initialize

How to set up the project (avocado init or cloning the reference).

## Install

How to install dependencies (avocado install).

## Build

How to build the project (avocado build).
Explain what the build step does for this specific reference.

## Deploy

How to provision and run on the target.
Include the correct provisioning profile for the target(s).

## Verify

How to confirm the reference is working.
What output to expect, how to observe it.

## Customize

How to modify the reference for the user's own needs.
What files to edit, what values to change.
```

## Guidelines

- **Be specific.** Include exact commands, expected output, and file paths.
- **Show, don't tell.** Use code blocks for commands and expected output.
- **Cover all targets.** If the reference supports multiple targets, note any differences in the deploy step (e.g., different provisioning profiles).
- **Keep it self-contained.** A user should be able to follow the guide without referencing other docs. Link to other docs for deep dives, but don't require them to complete the guide.
