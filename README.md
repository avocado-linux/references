# Avocado OS References

A collection of reference implementations for [Avocado OS](https://docs.peridio.com). Each reference is a complete, buildable project that demonstrates how to build, deploy, and run an application on Avocado OS using a specific language, framework, or hardware feature.

## Getting Started

Pick a reference and initialize a new project from it:

```bash
avocado init --reference <reference-name> my-project
cd my-project
avocado install -f
avocado build
avocado provision -r dev
```

See each reference's `getting_started.md` for target-specific instructions.

## Contributing

Community references are welcome! To submit a new reference, open a pull request with your reference directory added to this repository.

### Before submitting

1. Run `avocado clean` to remove all build artifacts
2. Verify your `.gitignore` covers build artifacts, `.avocado/`, `.avocado-state`, etc.
3. Follow the reference structure and documentation

### Reference structure

Every reference must include:

```
your-reference/
  README.md              # Required — metadata and summary
  getting_started.md     # Required — step-by-step guide
  icon.png               # Optional — display icon (PNG or SVG)
  avocado.yaml           # Project configuration
  .gitignore             # Build artifacts, .avocado/, .avocado-state
  app/                   # Application source
  app-compile.sh         # SDK compile step
  app-install.sh         # Install step
  app-clean.sh           # Clean step
```

See [spec_readme.md](./spec_readme.md) and [spec_getting_started.md](./spec_getting_started.md) for the required format and structure of `README.md` and `getting_started.md`.

